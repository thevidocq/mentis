"""Chats: each user sees only their own. The customer scope is chosen with the first message and never changes.

Who can chat: analysts and super-admins on any customer or "All customers";
tenant admins only on their own tenant (to check what analysts will get).
Log events carry metadata only, never questions or answers.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, current_user
from app.core.db import get_db
from app.models import Chat, ChatMessage, Role, Tenant, User
from app.models.base import utcnow
from app.services import answer as answering
from app.services.embeddings import EmbeddingError
from app.services.llm import LLMError
from app.services.logs import log_event

router = APIRouter(prefix="/chats", tags=["chats"])

MAX_QUESTION = 4000


# --- Schemas -------------------------------------------------------------------

class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    status: str
    citations: list
    followups: list
    tenants: list
    provider_name: str | None
    model: str | None
    latency_ms: int | None
    feedback: int | None
    created_at: datetime


class ChatSummary(BaseModel):
    id: uuid.UUID
    title: str
    scope_tenant_id: uuid.UUID | None
    scope_name: str
    updated_at: datetime


class ChatOut(ChatSummary):
    scope_available: bool
    messages: list[MessageOut]


class NewChat(BaseModel):
    tenant_id: uuid.UUID | None = None  # None = All customers
    message: str = Field(min_length=1, max_length=MAX_QUESTION)


class NewMessage(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_QUESTION)


class Rename(BaseModel):
    title: str = Field(min_length=1, max_length=120)


class Feedback(BaseModel):
    value: int | None  # 1, -1 or null to clear


class Exchange(BaseModel):
    chat: ChatSummary
    question: MessageOut
    answer: MessageOut


class ScopeOption(BaseModel):
    id: uuid.UUID | None
    name: str
    is_general: bool


# --- Helpers -------------------------------------------------------------------

def _scope_name(db: Session, chat: Chat) -> str:
    if chat.scope_tenant_id is None:
        return "All customers"
    t = db.get(Tenant, chat.scope_tenant_id)
    return t.name if t else "Deleted customer"


def _summary(db: Session, chat: Chat) -> ChatSummary:
    return ChatSummary(id=chat.id, title=chat.title, scope_tenant_id=chat.scope_tenant_id,
                       scope_name=_scope_name(db, chat), updated_at=chat.updated_at)


def _msg(m: ChatMessage) -> MessageOut:
    return MessageOut(id=m.id, role=m.role, content=m.content, status=m.status, citations=m.citations or [],
                      followups=m.followups or [], tenants=m.tenants or [], provider_name=m.provider_name,
                      model=m.model, latency_ms=m.latency_ms, feedback=m.feedback, created_at=m.created_at)


def _own_chat(db: Session, user: User, chat_id: uuid.UUID) -> Chat:
    chat = db.get(Chat, chat_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found.")
    return chat


def _check_scope(db: Session, user: User, tenant_id: uuid.UUID | None) -> None:
    if user.role == Role.TENANT_ADMIN:
        if tenant_id is None or tenant_id != user.tenant_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant admins can chat only on their own customer.")
    if tenant_id is not None:
        t = db.get(Tenant, tenant_id)
        if t is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found.")
        if t.status == "disabled":
            raise HTTPException(status.HTTP_409_CONFLICT, "This customer is disabled.")


def _scope_usable(db: Session, chat: Chat) -> bool:
    if chat.scope_tenant_id is None:
        return True
    t = db.get(Tenant, chat.scope_tenant_id)
    return t is not None and t.status != "disabled"


def _ask(db: Session, user: User, chat: Chat, question: str, first: bool, request: Request) -> Exchange:
    question = question.strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Write a question.")
    try:
        result = answering.answer(db, chat, question, first)
    except (LLMError, EmbeddingError) as e:
        result = answering.Answer(status="error", content=f"The answer could not be generated: {e}")
        log_event(db, "chat.error", kind="system", level="error", actor=user, tenant_id=chat.scope_tenant_id,
                  target=str(chat.id), detail={"error": str(e)[:300]}, commit=False)

    q = ChatMessage(chat_id=chat.id, role="user", content=question)
    db.add(q)
    db.flush()
    a = ChatMessage(chat_id=chat.id, role="assistant", content=result.content, status=result.status,
                    citations=result.citations, followups=result.followups, tenants=result.tenants,
                    provider_name=result.provider_name, model=result.model, latency_ms=result.latency_ms,
                    input_tokens=result.input_tokens, output_tokens=result.output_tokens)
    db.add(a)
    if first and result.title and not chat.title_locked:
        chat.title = result.title.strip()[:120] or chat.title
    chat.updated_at = utcnow()
    db.commit()
    # Metadata only: never the question or the answer.
    log_event(db, "chat.answered", actor=user, tenant_id=chat.scope_tenant_id, target=str(chat.id), ip=client_ip(request),
              detail={"status": result.status, "provider": result.provider_name, "model": result.model,
                      "latency_ms": result.latency_ms, "passages": result.passages, "citations": len(result.citations),
                      "input_tokens": result.input_tokens, "output_tokens": result.output_tokens})
    db.refresh(q)
    db.refresh(a)
    return Exchange(chat=_summary(db, chat), question=_msg(q), answer=_msg(a))


# --- Routes --------------------------------------------------------------------

@router.get("/scopes", response_model=list[ScopeOption])
def scopes(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[ScopeOption]:
    """What the user can pick with @. Tenant admins: only their tenant. General is not a scope: it is searched with the customers."""
    if user.role == Role.TENANT_ADMIN:
        t = db.get(Tenant, user.tenant_id) if user.tenant_id else None
        return [ScopeOption(id=t.id, name=t.name, is_general=False)] if t and t.status != "disabled" else []
    rows = db.scalars(select(Tenant).where(Tenant.status != "disabled", Tenant.is_global.is_(False)).order_by(Tenant.name)).all()
    return [ScopeOption(id=None, name="All customers", is_general=False)] + [ScopeOption(id=t.id, name=t.name, is_general=False) for t in rows]


@router.get("", response_model=list[ChatSummary])
def list_chats(q: str | None = Query(None, max_length=200), limit: int = Query(100, ge=1, le=500),
               db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[ChatSummary]:
    stmt = select(Chat).where(Chat.user_id == user.id)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        in_messages = select(ChatMessage.chat_id).where(ChatMessage.content.ilike(like))
        stmt = stmt.where(Chat.title.ilike(like) | Chat.id.in_(in_messages))
    chats = db.scalars(stmt.order_by(Chat.updated_at.desc()).limit(limit)).all()
    names = {t.id: t.name for t in db.scalars(select(Tenant))}
    return [ChatSummary(id=c.id, title=c.title, scope_tenant_id=c.scope_tenant_id, updated_at=c.updated_at,
                        scope_name="All customers" if c.scope_tenant_id is None else names.get(c.scope_tenant_id, "Deleted customer"))
            for c in chats]


@router.post("", response_model=Exchange, status_code=status.HTTP_201_CREATED)
def new_chat(body: NewChat, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Exchange:
    _check_scope(db, user, body.tenant_id)
    if body.tenant_id is not None and db.get(Tenant, body.tenant_id).is_global:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "General is searched with every customer; pick a customer or All customers.")
    chat = Chat(user_id=user.id, scope_tenant_id=body.tenant_id)
    db.add(chat)
    db.flush()
    return _ask(db, user, chat, body.message, True, request)


@router.get("/{chat_id}", response_model=ChatOut)
def get_chat(chat_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> ChatOut:
    chat = _own_chat(db, user, chat_id)
    msgs = db.scalars(select(ChatMessage).where(ChatMessage.chat_id == chat.id).order_by(ChatMessage.created_at, ChatMessage.role.desc())).all()
    s = _summary(db, chat)
    return ChatOut(**s.model_dump(), scope_available=_scope_usable(db, chat), messages=[_msg(m) for m in msgs])


@router.post("/{chat_id}/messages", response_model=Exchange)
def ask(chat_id: uuid.UUID, body: NewMessage, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> Exchange:
    chat = _own_chat(db, user, chat_id)
    # The scope is the chat's own; the request cannot change it.
    if not _scope_usable(db, chat):
        raise HTTPException(status.HTTP_409_CONFLICT, "The customer of this chat is no longer available. Start a new chat.")
    _check_scope(db, user, chat.scope_tenant_id)
    return _ask(db, user, chat, body.message, False, request)


@router.patch("/{chat_id}", response_model=ChatSummary)
def rename(chat_id: uuid.UUID, body: Rename, db: Session = Depends(get_db), user: User = Depends(current_user)) -> ChatSummary:
    chat = _own_chat(db, user, chat_id)
    title = body.title.strip()
    if not title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The title cannot be empty.")
    chat.title, chat.title_locked = title, True
    db.commit()
    return _summary(db, chat)


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(chat_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    chat = _own_chat(db, user, chat_id)
    db.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat.id))
    db.delete(chat)
    db.commit()


@router.post("/{chat_id}/messages/{message_id}/feedback", response_model=MessageOut)
def feedback(chat_id: uuid.UUID, message_id: uuid.UUID, body: Feedback, db: Session = Depends(get_db),
             user: User = Depends(current_user)) -> MessageOut:
    chat = _own_chat(db, user, chat_id)
    m = db.get(ChatMessage, message_id)
    if m is None or m.chat_id != chat.id or m.role != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found.")
    if body.value not in (1, -1, None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Feedback must be 1, -1 or null.")
    m.feedback = body.value
    db.commit()
    log_event(db, "chat.feedback", actor=user, tenant_id=chat.scope_tenant_id, target=str(m.id), detail={"value": body.value})
    return _msg(m)
