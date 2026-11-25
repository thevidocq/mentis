"""User management (super-admin: everyone; tenant admin: admins whose tenants are all its own)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.api.schemas import Name, TenantRef, UserOut
from app.core.db import get_db
from app.models import Chat, ChatMessage, Role, User, user_tenants
from app.services import sessions
from app.services import users as rules
from app.services.logs import log_event

router = APIRouter(prefix="/users", tags=["users"])
admins = require_roles(Role.SUPER_ADMIN, Role.TENANT_ADMIN)
super_admin = require_roles(Role.SUPER_ADMIN)


class UserAdminOut(UserOut):
    is_active: bool
    locked: bool
    manageable: bool = True


class UserUpdate(BaseModel):
    full_name: Name | None = None
    role: str | None = None
    tenant_ids: list[uuid.UUID] | None = None
    is_active: bool | None = None


def _out(u: User, actor: User | None = None) -> UserAdminOut:
    return UserAdminOut(
        id=u.id, email=u.email, full_name=u.full_name, role=u.role,
        tenants=[TenantRef(id=t.id, name=t.name) for t in u.tenants],
        totp_enabled=u.totp_enabled, preferences=u.preferences or {}, is_active=u.is_active,
        locked=sessions.is_locked(u), manageable=rules.can_manage(actor, u) if actor else True,
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
        # Admins sharing at least one tenant; only those entirely inside the actor's tenants are manageable.
        ids = actor.tenant_ids if tenant_id is None else ({tenant_id} & actor.tenant_ids)
        q = q.where(User.id.in_(select(user_tenants.c.user_id).where(user_tenants.c.tenant_id.in_(ids))))
    elif tenant_id is not None:
        q = q.where(User.id.in_(select(user_tenants.c.user_id).where(user_tenants.c.tenant_id == tenant_id)))
    return [_out(u, actor) for u in db.scalars(q)]


@router.patch("/{user_id}", response_model=UserAdminOut)
def update_user(user_id: uuid.UUID, body: UserUpdate, request: Request, db: Session = Depends(get_db), actor: User = Depends(admins)) -> UserAdminOut:
    target = _target(db, actor, user_id)
    changes: dict = {}

    if body.role is not None or body.tenant_ids is not None:
        new_role = body.role or target.role
        if body.tenant_ids is not None:
            new_ids = body.tenant_ids
        else:
            new_ids = list(target.tenant_ids) if new_role == Role.TENANT_ADMIN.value else []
        if actor.role != Role.SUPER_ADMIN.value:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a super-admin can change roles or tenants.")
        try:
            tenants = rules.check_role_assignment(db, actor, new_role, new_ids)
        except rules.RuleError as e:
            raise HTTPException(e.status, e.message) from None
        if new_role != target.role and rules.is_last_super_admin(db, target):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "There must be at least one active super-admin.")
        if new_role != target.role:
            changes["role"] = [target.role, new_role]
        old_names, new_names = sorted(t.name for t in target.tenants), sorted(t.name for t in tenants)
        if old_names != new_names:
            changes["tenants"] = [old_names, new_names]
        target.role, target.tenants = new_role, tenants

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
    if changes.get("is_active") is False or "role" in changes or "tenants" in changes:
        sessions.revoke_all_sessions(db, target)
    log_event(db, "user.updated", actor=actor, tenant_id=rules.single_tenant(target), target=target.email, ip=client_ip(request), detail=changes)
    return _out(target, actor)


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: User = Depends(admins)) -> None:
    target = _target(db, actor, user_id)
    if target.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "You cannot delete yourself.")
    if rules.is_last_super_admin(db, target):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "There must be at least one active super-admin.")
    email, tid = target.email, rules.single_tenant(target)
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
    target.totp_secret_enc, target.totp_enabled, target.totp_last_step = None, False, None
    db.commit()
    sessions.revoke_all_sessions(db, target)
    log_event(db, "user.mfa_reset", actor=actor, tenant_id=rules.single_tenant(target), target=target.email, ip=client_ip(request))
