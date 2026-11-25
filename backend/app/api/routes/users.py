"""User management (super-admin: everyone; tenant admin: admins of its own tenant)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.api.schemas import UserOut
from app.core.db import get_db
from app.models import Chat, ChatMessage, Role, User
from app.services import sessions
from app.services import users as rules
from app.services.logs import log_event

router = APIRouter(prefix="/users", tags=["users"])
admins = require_roles(Role.SUPER_ADMIN, Role.TENANT_ADMIN)
super_admin = require_roles(Role.SUPER_ADMIN)


class UserAdminOut(UserOut):
    is_active: bool
    locked: bool


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = None
    tenant_id: uuid.UUID | None = None
    is_active: bool | None = None


def _out(u: User) -> UserAdminOut:
    return UserAdminOut(
        id=u.id, email=u.email, full_name=u.full_name, role=u.role, tenant_id=u.tenant_id,
        totp_enabled=u.totp_enabled, preferences=u.preferences or {}, is_active=u.is_active,
        locked=sessions.is_locked(u),
    )


def _target(db: Session, actor: User, user_id: uuid.UUID) -> User:
    target = db.get(User, user_id)
    if target is None or not rules.can_manage(actor, target):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    return target


@router.get("", response_model=list[UserAdminOut])
def list_users(tenant_id: uuid.UUID | None = None, db: Session = Depends(get_db), actor: User = Depends(admins)) -> list[UserAdminOut]:
    q = select(User).order_by(User.full_name)
    if actor.role == Role.TENANT_ADMIN.value:
        q = q.where(User.tenant_id == actor.tenant_id)
    elif tenant_id is not None:
        q = q.where(User.tenant_id == tenant_id)
    return [_out(u) for u in db.scalars(q)]


@router.patch("/{user_id}", response_model=UserAdminOut)
def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request, db: Session = Depends(get_db), actor: User = Depends(admins)) -> UserAdminOut:
    target = _target(db, actor, user_id)
    changes: dict = {}

    if body.role is not None or "tenant_id" in body.model_fields_set:
        new_role = body.role or target.role
        new_tenant = body.tenant_id if "tenant_id" in body.model_fields_set else target.tenant_id
        if new_role != Role.TENANT_ADMIN.value and "tenant_id" not in body.model_fields_set:
            new_tenant = None
        if actor.role != Role.SUPER_ADMIN.value:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a super-admin can change roles or tenants.")
        try:
            rules.check_role_assignment(db, actor, new_role, new_tenant)
        except rules.RuleError as e:
            raise HTTPException(e.status, e.message) from None
        if new_role != target.role and rules.is_last_super_admin(db, target):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "There must be at least one active super-admin.")
        changes.update(role=[target.role, new_role], tenant_id=[str(target.tenant_id), str(new_tenant)])
        target.role, target.tenant_id = new_role, new_tenant

    if body.full_name is not None:
        changes["full_name"] = [target.full_name, body.full_name.strip()]
        target.full_name = body.full_name.strip()

    if body.is_active is not None and body.is_active != target.is_active:
        if not body.is_active and target.id == actor.id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot deactivate yourself.")
        if not body.is_active and rules.is_last_super_admin(db, target):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "There must be at least one active super-admin.")
        target.is_active = body.is_active
        changes["is_active"] = body.is_active

    db.commit()
    if changes.get("is_active") is False or "role" in changes:
        sessions.revoke_all_sessions(db, target)
    log_event(db, "user.updated", actor=actor, tenant_id=target.tenant_id, target=target.email, ip=client_ip(request), detail=changes)
    return _out(target)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: User = Depends(admins)) -> None:
    target = _target(db, actor, user_id)
    if target.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete yourself.")
    if rules.is_last_super_admin(db, target):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There must be at least one active super-admin.")
    email, tid = target.email, target.tenant_id
    sessions.revoke_all_sessions(db, target)
    chat_ids = select(Chat.id).where(Chat.user_id == target.id)
    db.execute(delete(ChatMessage).where(ChatMessage.chat_id.in_(chat_ids)))
    db.execute(delete(Chat).where(Chat.user_id == target.id))
    db.delete(target)
    db.commit()
    log_event(db, "user.deleted", level="warning", actor=actor, tenant_id=tid, target=email, ip=client_ip(request))


@router.post("/{user_id}/reset-2fa", status_code=status.HTTP_204_NO_CONTENT)
def reset_2fa(user_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: User = Depends(super_admin)) -> None:
    target = _target(db, actor, user_id)
    target.totp_secret_enc, target.totp_enabled = None, False
    db.commit()
    sessions.revoke_all_sessions(db, target)
    log_event(db, "user.mfa_reset", actor=actor, tenant_id=target.tenant_id, target=target.email, ip=client_ip(request))
