"""Chats: each user sees only their own. The customer scope is chosen with the first message and never changes.

Who can chat: analysts and super-admins on any customer or "All customers";
tenant admins only on their own tenant (to check what analysts will get).
Log events carry metadata only, never questions or answers.
"""

import logging
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.core.db import get_db
from app.models import Chat, ChatMessage, ChatShare, Role, Tenant, User
from app.models.base import utcnow
from app.services import access, answer_check, chat_visibility, integrations
from app.services.answer_check import runner as check_runner
from app.services import answer as answering
from app.services.embeddings import EmbeddingError
from app.services.llm import LLMError
from app.services.vector_index import VectorIndexError
from app.services.logs import log_event
from app.services.public_errors import public_message

_log = logging.getLogger("mentis.chats")
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
    check: dict | None = None  # answer check result (see services/answer_check)


class ChatSummary(BaseModel):
    id: uuid.UUID
    title: str
    scope_tenant_id: uuid.UUID | None
    scope_name: str
    updated_at: datetime
    use_general: bool = True  # General Knowledge Base searched with the customer
    integration_ids: list[uuid.UUID] = []  # integrations chosen with #


class ChatOut(ChatSummary):
    scope_available: bool
    shared: bool = False  # an active share link exists
    messages: list[MessageOut]


class NewChat(BaseModel):
    tenant_id: uuid.UUID | None = None  # None = All customers
    use_general: bool = True            # turned off only explicitly by the user
    integration_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)  # # integrations of the customer
    message: str = Field(min_length=1, max_length=MAX_QUESTION)


class NewMessage(BaseModel):
    message: str = Field(min_length=1, max_length=MAX_QUESTION)


class Rename(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    use_general: bool | None = None
    integration_ids: list[uuid.UUID] | None = Field(default=None, max_length=20)


class Feedback(BaseModel):
    value: int | None  # 1, -1 or null to clear


class Exchange(BaseModel):
    chat: ChatSummary
    question: MessageOut
    answer: MessageOut


class IntegrationOption(BaseModel):
    id: uuid.UUID
    name: str
    product: str
    type: str  # ticketing | edr | siem


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
                       scope_name=_scope_name(db, chat), updated_at=chat.updated_at, use_general=chat.use_general,
                       integration_ids=_chat_integrations(db, chat))


def _chat_integrations(db: Session, chat: Chat) -> list[uuid.UUID]:
    """The chat's # integrations that are still usable (a removed or disabled one disappears)."""
    return [i.id for i, _ in integrations.for_chat(db, chat)]


def _check_integrations(db: Session, tenant_id: uuid.UUID | None, ids: list[uuid.UUID]) -> list[str]:
    """# integrations must belong to the chat's own customer and be usable; returns them as strings."""
    if not ids:
        return []
    tenant = db.get(Tenant, tenant_id) if tenant_id is not None else None
    if tenant is None or tenant.is_global:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Integrations can be used only in a chat on one customer.")
    usable = {i.id for i, _ in integrations.selectable(db, tenant)}
    if any(i not in usable for i in ids):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This integration is not available for this customer.")
    return [str(i) for i in dict.fromkeys(ids)]


def _msg(m: ChatMessage, hidden: bool = False) -> MessageOut:
    """`hidden`: the answer used a customer no longer assigned to the user (see chat_visibility)."""
    if hidden:
        return MessageOut(id=m.id, role=m.role, content=chat_visibility.HIDDEN, status=m.status, citations=[],
                          followups=[], tenants=[], provider_name=m.provider_name, model=m.model,
                          latency_ms=m.latency_ms, feedback=m.feedback, created_at=m.created_at)
    return MessageOut(id=m.id, role=m.role, content=m.content, status=m.status, citations=m.citations or [],
                      followups=m.followups or [], tenants=m.tenants or [], provider_name=m.provider_name,
                      model=m.model, latency_ms=m.latency_ms, feedback=m.feedback, created_at=m.created_at,
                      check=answer_check.public(m.check, m.created_at) if m.role == "assistant" else None)


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


def _ask(db: Session, user: User, chat: Chat, question: str, first: bool, request: Request,
         background: BackgroundTasks | None = None) -> Exchange:
    question = question.replace("\x00", "").strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Write a question.")
    try:
        result = answering.answer(db, chat, question, first)
    except (LLMError, EmbeddingError, VectorIndexError) as e:
        # The user gets a plain message; the details (addresses, provider replies) go to the logs only.
        result = answering.Answer(status="error", content=f"The answer could not be generated: {public_message(e)}")
        log_event(db, "chat.error", kind="system", level="error", actor=user, tenant_id=chat.scope_tenant_id,
                  target=str(chat.id), detail={"error": str(e)[:300]}, commit=False)

    # Answer check: level 1 now; level 2 now ("hide") or after the response ("warn").
    try:
        result, check, later = check_runner.before_save(
            db, chat, question, first, result,
            lambda problems: answering.answer(db, chat, question, first, correction=problems, live=result.live))
    except (LLMError, EmbeddingError, VectorIndexError):
        check, later = {"level2": "unavailable", "issues": [], "checker": None}, False
    except Exception:  # noqa: BLE001 - a broken check must never lose the answer
        _log.exception("answer check failed")
        check, later = {"level2": "unavailable", "issues": [], "checker": None}, False

    q = ChatMessage(chat_id=chat.id, role="user", content=question)
    db.add(q)
    db.flush()
    content = result.content
    # Added after the check: links to the records found, and lookups that failed or found nothing.
    if result.live_links and result.status == "ok" and result.citations:  # not under a hidden answer
        content += "\n\nOpen: " + " · ".join(f"[{label.replace('[', '(').replace(']', ')')}]({url})"
                                           for label, url in result.live_links)
    if result.live_notes:
        content += "\n\n" + "\n".join(f"*{n}*" for n in result.live_notes)
    a = ChatMessage(chat_id=chat.id, role="assistant", content=content, status=result.status,
                    citations=result.citations, followups=result.followups, tenants=result.tenants,
                    provider_name=result.provider_name, model=result.model, latency_ms=result.latency_ms,
                    input_tokens=result.input_tokens, output_tokens=result.output_tokens, check=check)
    db.add(a)
    if first and result.title and not chat.title_locked:
        chat.title = result.title.strip()[:120] or chat.title
    chat.updated_at = utcnow()
    db.commit()
    # Metadata only: never the question or the answer.
    log_event(db, "chat.answered", actor=user, tenant_id=chat.scope_tenant_id, target=str(chat.id), ip=client_ip(request),
              detail={"status": result.status, "provider": result.provider_name, "model": result.model,
                      "latency_ms": result.latency_ms, "passages": result.passages, "citations": len(result.citations),
                      "integration_calls": result.live_calls,
                      "input_tokens": result.input_tokens, "output_tokens": result.output_tokens})
    db.refresh(q)
    db.refresh(a)
    if later and background is not None:
        background.add_task(check_runner.after_save, a.id, chat.id, result)
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


@router.get("/integrations", response_model=list[IntegrationOption])
def chat_integrations(tenant_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(readers)) -> list[IntegrationOption]:
    """What the user can pick with # in a chat on this customer."""
    _check_scope(db, user, tenant_id)
    tenant = db.get(Tenant, tenant_id)
    return [IntegrationOption(id=i.id, name=i.name, product=c.manifest.label, type=c.manifest.type)
            for i, c in integrations.selectable(db, tenant)]


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
    return [ChatSummary(id=c.id, title=c.title, scope_tenant_id=c.scope_tenant_id, updated_at=c.updated_at, use_general=c.use_general,
                        integration_ids=[uuid.UUID(i) for i in (c.integration_ids or [])],
                        scope_name=every if c.scope_tenant_id is None else names.get(c.scope_tenant_id, "Deleted customer"))
            for c in chats]


@router.post("", response_model=Exchange, status_code=status.HTTP_201_CREATED)
def new_chat(body: NewChat, request: Request, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(readers)) -> Exchange:
    _check_scope(db, user, body.tenant_id)
    chosen = _check_integrations(db, body.tenant_id, body.integration_ids)
    chat = Chat(user_id=user.id, scope_tenant_id=body.tenant_id, use_general=body.use_general, integration_ids=chosen)
    db.add(chat)
    db.flush()
    if chosen:
        log_event(db, "chat.integrations", actor=user, tenant_id=chat.scope_tenant_id, target=str(chat.id),
                  detail={"integrations": chosen}, commit=False)
    return _ask(db, user, chat, body.message, True, request, background)


@router.get("/{chat_id}", response_model=ChatOut)
def get_chat(chat_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(readers)) -> ChatOut:
    chat = _own_chat(db, user, chat_id)
    msgs = db.scalars(select(ChatMessage).where(ChatMessage.chat_id == chat.id).order_by(ChatMessage.created_at, ChatMessage.role.desc())).all()
    s = _summary(db, chat)
    vis = chat_visibility.Visibility(db, user)
    shared = db.scalar(select(ChatShare.id).where(ChatShare.chat_id == chat.id, ChatShare.revoked_at.is_(None),
                                                  ChatShare.expires_at > utcnow()).limit(1)) is not None
    return ChatOut(**s.model_dump(), scope_available=_scope_usable(db, chat, user), shared=shared,
                   messages=[_msg(m, vis.hidden(chat, m)) for m in msgs])


@router.post("/{chat_id}/messages", response_model=Exchange)
def ask(chat_id: uuid.UUID, body: NewMessage, request: Request, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(readers)) -> Exchange:
    chat = _own_chat(db, user, chat_id)
    # The scope is the chat's own; the request cannot change it.
    if not _scope_usable(db, chat, user):
        raise HTTPException(status.HTTP_409_CONFLICT, "The customer of this chat is no longer available. Start a new chat.")
    _check_scope(db, user, chat.scope_tenant_id)
    return _ask(db, user, chat, body.message, False, request, background)


@router.patch("/{chat_id}", response_model=ChatSummary)
def rename(chat_id: uuid.UUID, body: Rename, db: Session = Depends(get_db), user: User = Depends(readers)) -> ChatSummary:
    """Rename the chat, turn the General Knowledge Base on or off, or change its # integrations."""
    chat = _own_chat(db, user, chat_id)
    if body.title is not None:
        title = body.title.strip()
        if not title:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The title cannot be empty.")
        chat.title, chat.title_locked = title, True
    if body.use_general is not None and body.use_general != chat.use_general:
        chat.use_general = body.use_general
        log_event(db, "chat.general_knowledge", actor=user, tenant_id=chat.scope_tenant_id, target=str(chat.id),
                  detail={"use_general": chat.use_general}, commit=False)
    if body.integration_ids is not None:
        chosen = _check_integrations(db, chat.scope_tenant_id, body.integration_ids)
        if chosen != list(chat.integration_ids or []):
            chat.integration_ids = chosen
            log_event(db, "chat.integrations", actor=user, tenant_id=chat.scope_tenant_id, target=str(chat.id),
                      detail={"integrations": chosen}, commit=False)
    db.commit()
    return _summary(db, chat)


@router.delete("/{chat_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_chat(chat_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(readers)) -> None:
    chat = _own_chat(db, user, chat_id)
    db.execute(delete(ChatMessage).where(ChatMessage.chat_id == chat.id))
    db.execute(delete(ChatShare).where(ChatShare.chat_id == chat.id))  # its links stop working
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
