"""Share a chat by link with colleagues signed in to Mentis (read-only).

A link is not a public page: the viewer must be signed in as a tenant admin or analyst and must see
the chat's customer (for an "All customers" chat: every customer of the owner). Answers that used a customer the viewer does not see are hidden together with
their question. Links expire, can be revoked, and every creation, revocation and view is logged.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.api.routes.chats import MessageOut, _msg, _own_chat, _scope_name
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import hash_token, new_session_token
from app.models import Chat, ChatMessage, ChatShare, Role, User
from app.models.base import utcnow
from app.services import access, chat_visibility
from app.services.logs import log_event

router = APIRouter(tags=["chat sharing"])
readers = require_roles(Role.TENANT_ADMIN, Role.ANALYST)
NOT_AVAILABLE = "This link is invalid, revoked or expired, or the chat is not available to you."


class ShareOut(BaseModel):
    url: str | None = None          # only when just created (the token is not stored)
    active: bool
    expires_at: datetime | None = None


class SharedChat(BaseModel):
    title: str
    scope_name: str
    owner_name: str
    messages: list[MessageOut]
    hidden: int                     # exchanges left out because the viewer does not see their customer


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _active(db: Session, chat_id: uuid.UUID) -> ChatShare | None:
    row = db.scalar(select(ChatShare).where(ChatShare.chat_id == chat_id, ChatShare.revoked_at.is_(None))
                    .order_by(ChatShare.created_at.desc()).limit(1))
    return row if row is not None and _aware(row.expires_at) > utcnow() else None


def _may_view(db: Session, viewer: User, owner: User, chat: Chat) -> bool:
    if chat.scope_tenant_id is not None:
        return access.sees(db, viewer, chat.scope_tenant_id)
    return access.tenant_ids(db, owner) <= access.tenant_ids(db, viewer)


@router.get("/chats/{chat_id}/share", response_model=ShareOut)
def share_state(chat_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(readers)) -> ShareOut:
    chat = _own_chat(db, user, chat_id)
    row = _active(db, chat.id)
    return ShareOut(active=row is not None, expires_at=row.expires_at if row else None)


@router.post("/chats/{chat_id}/share", response_model=ShareOut, status_code=status.HTTP_201_CREATED)
def create_share(chat_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(readers)) -> ShareOut:
    """A new link replaces the chat's previous one."""
    chat = _own_chat(db, user, chat_id)
    db.execute(update(ChatShare).where(ChatShare.chat_id == chat.id, ChatShare.revoked_at.is_(None)).values(revoked_at=utcnow()))
    token = new_session_token()
    expires = utcnow() + timedelta(days=get_settings().chat_share_days)
    db.add(ChatShare(chat_id=chat.id, token_hash=hash_token(token), created_by=user.id, expires_at=expires))
    log_event(db, "chat.shared", actor=user, tenant_id=chat.scope_tenant_id, target=str(chat.id), ip=client_ip(request),
              detail={"days": get_settings().chat_share_days}, commit=False)
    db.commit()
    return ShareOut(url=f"{get_settings().public_url.rstrip('/')}/shared/{token}", active=True, expires_at=expires)


@router.delete("/chats/{chat_id}/share", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share(chat_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(readers)) -> None:
    chat = _own_chat(db, user, chat_id)
    db.execute(update(ChatShare).where(ChatShare.chat_id == chat.id, ChatShare.revoked_at.is_(None)).values(revoked_at=utcnow()))
    log_event(db, "chat.share_revoked", actor=user, tenant_id=chat.scope_tenant_id, target=str(chat.id), ip=client_ip(request), commit=False)
    db.commit()


@router.get("/shared/{token}", response_model=SharedChat)
def view_shared(token: str, request: Request, db: Session = Depends(get_db), user: User = Depends(readers)) -> SharedChat:
    row = db.scalar(select(ChatShare).where(ChatShare.token_hash == hash_token(token)))
    if row is None or row.revoked_at is not None or _aware(row.expires_at) < utcnow():
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_AVAILABLE)
    chat = db.get(Chat, row.chat_id)
    owner = db.get(User, chat.user_id) if chat else None
    # The owner must still be active, and the viewer must see the chat's customer. An "All customers"
    # chat searched every customer of the owner, and an answer can draw on passages it does not cite:
    # the viewer must see all of them.
    if chat is None or owner is None or not owner.is_active or not _may_view(db, user, owner, chat):
        log_event(db, "chat.share_denied", level="warning", actor=user, target=str(row.chat_id), ip=client_ip(request))
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_AVAILABLE)
    msgs = db.scalars(select(ChatMessage).where(ChatMessage.chat_id == chat.id)
                      .order_by(ChatMessage.created_at, ChatMessage.role.desc())).all()
    vis = chat_visibility.Visibility(db, user)  # what the VIEWER may read
    out, hidden = [], 0
    for i, m in enumerate(msgs):
        if m.role == "user":
            answer = msgs[i + 1] if i + 1 < len(msgs) and msgs[i + 1].role == "assistant" else None
            if answer is not None and vis.hidden(chat, answer):
                hidden += 1
                continue  # the question could reveal the other customer too
            out.append(_msg(m))
        elif not vis.hidden(chat, m):
            out.append(_msg(m).model_copy(update={"feedback": None}))  # the owner's rating stays private
    log_event(db, "chat.share_viewed", actor=user, tenant_id=chat.scope_tenant_id, target=str(chat.id), ip=client_ip(request),
              detail={"owner": owner.email})
    return SharedChat(title=chat.title, scope_name=_scope_name(db, chat), owner_name=owner.full_name, messages=out, hidden=hidden)
