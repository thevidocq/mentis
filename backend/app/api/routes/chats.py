"""Chats: each user sees only their own. The customer scope is chosen with the first message and never changes.

Who can chat: analysts and super-admins on any customer or "All customers";
tenant admins only on their own tenant (to check what analysts will get).
Log events carry metadata only, never questions or answers.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.core.db import get_db
from app.models import Chat, ChatMessage, Role, Tenant, User
from app.models.base import utcnow
from app.services import access, chat_visibility
from app.services import answer as answering
from app.services.embeddings import EmbeddingError
from app.services.llm import LLMError
from app.services.vector_index import VectorIndexError
from app.services.logs import log_event
from app.services.public_errors import public_message

router = APIRouter(prefix="/chats", tags=["chats"])
# Super-admins manage the platform: no chat, no customer content.
readers = require_roles(Role.TENANT_ADMIN, Role.ANALYST)

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
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


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
        return answering.all_label(db.get(User, chat.user_id))
    t = db.get(Tenant, chat.scope_tenant_id)
    return t.name if t else "Deleted customer"


def _summary(db: Session, chat: Chat) -> ChatSummary:
    return ChatSummary(id=chat.id, title=chat.title, scope_tenant_id=chat.scope_tenant_id,
                       scope_name=_scope_name(db, chat), updated_at=chat.updated_at)


def _msg(m: ChatMessage, hidden: bool = False) -> MessageOut:
    """`hidden`: the answer used a customer no longer assigned to the user (see chat_visibility)."""
    if hidden:
        return MessageOut(id=m.id, role=m.role, content=chat_visibility.HIDDEN, status=m.status, citations=[],
                          followups=[], tenants=[], provider_name=m.provider_name, model=m.model,
                          latency_ms=m.latency_ms, feedback=m.feedback, created_at=m.created_at)
    return MessageOut(id=m.id, role=m.role, content=m.content, status=m.status, citations=m.citations or [],
                      followups=m.followups or [], tenants=m.tenants or [], provider_name=m.provider_name,
                      model=m.model, latency_ms=m.latency_ms, feedback=m.feedback, created_at=m.created_at)


def _own_chat(db: Session, user: User, chat_id: uuid.UUID) -> Chat:
    chat = db.get(Chat, chat_id)
    if chat is None or chat.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Chat not found.")
    return chat


def _check_scope(db: Session, user: User, tenant_id: uuid.UUID | None) -> None:
    if tenant_id is not None and not access.sees(db, user, tenant_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This customer is not assigned to you.")
    if tenant_id is not None:
        t = db.get(Tenant, tenant_id)
        if t is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found.")
        if t.status == "disabled":
            raise HTTPException(status.HTTP_409_CONFLICT, "This customer is disabled.")


def _scope_usable(db: Session, chat: Chat, user: User) -> bool:
    """The chat's customer still exists, is not disabled and is still assigned to the user."""
    if chat.scope_tenant_id is None:
        return True
    t = db.get(Tenant, chat.scope_tenant_id)
    return t is not None and t.status != "disabled" and access.sees(db, user, t.id)


def _ask(db: Session, user: User, chat: Chat, question: str, first: bool, request: Request) -> Exchange:
    question = question.strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Write a question.")
    try:
        result = answering.answer(db, chat, question, first)
    except (LLMError, EmbeddingError, VectorIndexError) as e:
        # The user gets a plain message; the details (addresses, provider replies) go to the logs only.
        result = answering.Answer(status="error", content=f"The answer could not be generated: {public_message(e)}")
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
def scopes(db: Session = Depends(get_db), user: User = Depends(readers)) -> list[ScopeOption]:
    """What the user can pick with @: its customers, then General alone (to test the shared documentation).

    With a customer, General is searched too (unless that customer turns it off).
    """
    visible = [t for t in access.tenants(db, user) if t.status != "disabled"]
    own = [t for t in visible if not t.is_global]
    general = [t for t in visible if t.is_global]
    label = answering.all_label(user)
    head = [ScopeOption(id=None, name=label, is_general=False)] if len(own) > 1 or user.all_tenants else []
    return (head + [ScopeOption(id=t.id, name=t.name, is_general=False) for t in own]
            + [ScopeOption(id=t.id, name=t.name, is_general=True) for t in general])


@router.get("", response_model=list[ChatSummary])
def list_chats(q: str | None = Query(None, max_length=200), limit: int = Query(100, ge=1, le=500),
               db: Session = Depends(get_db), user: User = Depends(readers)) -> list[ChatSummary]:
    stmt = select(Chat).where(Chat.user_id == user.id)
    if q and q.strip():
        like = f"%{q.strip().lower()}%"
        # Questions are the user's own; answers are searched only in chats on a customer the user
        # still sees, so search cannot hint at answers hidden after an access change.
        visible = list(access.tenant_ids(db, user))
        in_questions = select(ChatMessage.chat_id).where(ChatMessage.role == "user", ChatMessage.content.ilike(like))
        in_answers = (select(ChatMessage.chat_id).join(Chat, Chat.id == ChatMessage.chat_id)
                      .where(ChatMessage.role == "assistant", ChatMessage.content.ilike(like), Chat.scope_tenant_id.in_(visible)))
        stmt = stmt.where(Chat.title.ilike(like) | Chat.id.in_(in_questions) | Chat.id.in_(in_answers))
    chats = db.scalars(stmt.order_by(Chat.updated_at.desc()).limit(limit)).all()
    names = {t.id: t.name for t in db.scalars(select(Tenant))}
    every = answering.all_label(user)
    return [ChatSummary(id=c.id, title=c.title, scope_tenant_id=c.scope_tenant_id, updated_at=c.updated_at,
                        scope_name=every if c.scope_tenant_id is None else names.get(c.scope_tenant_id, "Deleted customer"))
            for c in chats]


@router.post("", response_model=Exchange, status_code=status.HTTP_201_CREATED)
def new_chat(body: NewChat, request: Request, db: Session = Depends(get_db), user: User = Depends(readers)) -> Exchange:
    _check_scope(db, user, body.tenant_id)
    chat = Chat(user_id=user.id, scope_tenant_id=body.tenant_id)
    db.add(chat)
    db.flush()
    return _ask(db, user, chat, body.message, True, request)


@router.get("/{chat_id}", response_model=ChatOut)
def get_chat(chat_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(readers)) -> ChatOut:
    chat = _own_chat(db, user, chat_id)
    msgs = db.scalars(select(ChatMessage).where(ChatMessage.chat_id == chat.id).order_by(ChatMessage.created_at, ChatMessage.role.desc())).all()
    s = _summary(db, chat)
    vis = chat_visibility.Visibility(db, user)
    return ChatOut(**s.model_dump(), scope_available=_scope_usable(db, chat, user),
                   messages=[_msg(m, vis.hidden(chat, m)) for m in msgs])


@router.post("/{chat_id}/messages", response_model=Exchange)
def ask(chat_id: uuid.UUID, body: NewMessage, request: Request, db: Session = Depends(get_db), user: User = Depends(readers)) -> Exchange:
    chat = _own_chat(db, user, chat_id)
    # The scope is the chat's own; the request cannot change it.
    if not _scope_usable(db, chat, user):
        raise HTTPException(status.HTTP_409_CONFLICT, "The customer of this chat is no longer available. Start a new chat.")
    _check_scope(db, user, chat.scope_tenant_id)
    return _ask(db, user, chat, body.message, False, request)


@router.patch("/{chat_id}", response_model=ChatSummary)
def rename(chat_id: uuid.UUID, body: Rename, db: Session = Depends(get_db), user: User = Depends(readers)) -> ChatSummary:
    chat = _own_chat(db, user, chat_id)
    title = body.title.strip()
    if not title:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The title cannot be empty.")
    chat.title, chat.title_locked = title, True
    db.commit()
    return _summary(db, chat)


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(chat_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(readers)) -> None:
    chat = _own_chat(db, user, chat_id)
    db.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat.id))
    db.delete(chat)
    db.commit()


@router.post("/{chat_id}/messages/{message_id}/feedback", response_model=MessageOut)
def feedback(chat_id: uuid.UUID, message_id: uuid.UUID, body: Feedback, db: Session = Depends(get_db),
             user: User = Depends(readers)) -> MessageOut:
    chat = _own_chat(db, user, chat_id)
    m = db.get(ChatMessage, message_id)
    if m is None or m.chat_id != chat.id or m.role != "assistant":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found.")
    if body.value not in (1, -1, None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Feedback must be 1, -1 or null.")
    m.feedback = body.value
    db.commit()
    log_event(db, "chat.feedback", actor=user, tenant_id=chat.scope_tenant_id, target=str(m.id), detail={"value": body.value})
    return _msg(m, chat_visibility.Visibility(db, user).hidden(chat, m))
