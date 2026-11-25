"""Invitations: admins invite users by email; the invitee sets a password through the link."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.api.schemas import Name, TenantRef
from app.core.db import get_db
from app.core.security import password_problem
from app.models import Invitation, Role, Tenant, User
from app.services import access
from app.services import invitations as svc
from app.services import users as rules
from app.services.logs import log_event

router = APIRouter(prefix="/invitations", tags=["invitations"])
admins = require_roles(Role.SUPER_ADMIN, Role.TENANT_ADMIN)


class InviteCreate(BaseModel):
    email: EmailStr
    full_name: Name
    role: str
    tenant_ids: list[uuid.UUID] = []
    all_tenants: bool = False


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    tenants: list[TenantRef]
    all_tenants: bool
    expires_at: datetime


class InviteCreated(InviteOut):
    email_sent: bool
    # Returned only when the email could not be sent, so the admin can share the link manually.
    invite_url: str | None = None


class InviteInfo(BaseModel):
    email: str
    full_name: str
    role: str
    tenant_names: list[str]
    all_tenants: bool = False


class InviteAccept(BaseModel):
    password: str


def _ids(inv: Invitation) -> set[uuid.UUID]:
    return {uuid.UUID(t) for t in inv.tenant_ids or []}


def _out(db: Session, inv: Invitation) -> dict:
    ids = _ids(inv)
    tenants = [TenantRef(id=t.id, name=t.name, is_general=t.is_global)
               for t in db.scalars(select(Tenant).where(Tenant.id.in_(ids)).order_by(Tenant.is_global.desc(), Tenant.name))] if ids else []
    return dict(id=inv.id, email=inv.email, full_name=inv.full_name, role=inv.role, tenants=tenants,
                all_tenants=inv.all_tenants, expires_at=inv.expires_at)


def _manageable(db: Session, actor: User, inv: Invitation) -> bool:
    return actor.role == Role.SUPER_ADMIN.value or (inv.role in rules.CONTENT_ROLES and access.covers(db, actor, _ids(inv), inv.all_tenants))


@router.post("", response_model=InviteCreated, status_code=status.HTTP_201_CREATED)
def create_invitation(body: InviteCreate, request: Request, db: Session = Depends(get_db), actor: User = Depends(admins)) -> InviteCreated:
    email = body.email.lower()
    try:
        tenants = rules.check_role_assignment(db, actor, body.role, body.tenant_ids, body.all_tenants)
    except rules.RuleError as e:
        raise HTTPException(e.status, e.message) from None
    if rules.email_in_use(db, email):
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")
    # A new invitation replaces the pending one: only if the actor could revoke that one too.
    pending = db.scalar(select(Invitation).where(Invitation.email == email, Invitation.accepted_at.is_(None)))
    if pending is not None and not _manageable(db, actor, pending):
        raise HTTPException(status.HTTP_409_CONFLICT, "This email already has a pending invitation from another admin.")

    inv, token = svc.create(db, email=email, full_name=body.full_name.strip(), role=body.role,
                            tenant_ids=[str(t.id) for t in tenants], all_tenants=body.all_tenants and body.role in rules.CONTENT_ROLES,
                            invited_by=actor.id)
    sent = svc.send(db, inv, token)
    log_event(db, "user.invited", actor=actor, tenant_id=tenants[0].id if len(tenants) == 1 else None, target=email,
              ip=client_ip(request), detail={"role": inv.role, "tenants": [t.name for t in tenants], "all_tenants": inv.all_tenants, "email_sent": sent})
    return InviteCreated(**_out(db, inv), email_sent=sent, invite_url=None if sent else svc.invite_url(token))


@router.get("", response_model=list[InviteOut])
def list_invitations(db: Session = Depends(get_db), actor: User = Depends(admins)) -> list[InviteOut]:
    q = select(Invitation).where(Invitation.accepted_at.is_(None)).order_by(Invitation.created_at.desc())
    invs = list(db.scalars(q))
    if actor.role == Role.TENANT_ADMIN.value:
        invs = [i for i in invs if _manageable(db, actor, i)]
    return [InviteOut(**_out(db, i)) for i in invs]


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(invitation_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: User = Depends(admins)) -> None:
    inv = db.get(Invitation, invitation_id)
    if inv is None or not _manageable(db, actor, inv):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found.")
    db.delete(inv)
    db.commit()
    log_event(db, "user.invitation_revoked", actor=actor, target=inv.email, ip=client_ip(request))


# --- Public endpoints used by the invitee (no session) -------------------------

@router.get("/accept/{token}", response_model=InviteInfo)
def invitation_info(token: str, db: Session = Depends(get_db)) -> InviteInfo:
    inv = svc.find_valid(db, token)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invitation is invalid or has expired.")
    return InviteInfo(email=inv.email, full_name=inv.full_name, role=inv.role, tenant_names=[t.name for t in _out(db, inv)["tenants"]], all_tenants=inv.all_tenants)


@router.post("/accept/{token}", status_code=status.HTTP_201_CREATED)
def accept_invitation(token: str, body: InviteAccept, request: Request, db: Session = Depends(get_db)) -> dict:
    inv = svc.find_valid(db, token)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invitation is invalid or has expired.")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(422, problem)
    if rules.email_in_use(db, inv.email):
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")
    if inv.role in rules.CONTENT_ROLES and not inv.all_tenants and not svc.tenants_of(db, inv):
        raise HTTPException(status.HTTP_409_CONFLICT, "The customers of this invitation no longer exist. Ask for a new invitation.")
    user = svc.accept(db, inv, body.password)
    log_event(db, "user.invitation_accepted", actor=user, ip=client_ip(request))
    return {"email": user.email, "next": "login"}
