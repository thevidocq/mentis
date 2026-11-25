"""Invitations: admins invite users by email; the invitee sets a password through the link."""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.core.db import get_db
from app.core.security import password_problem
from app.models import Invitation, Role, Tenant, User
from app.services import invitations as svc
from app.services import users as rules
from app.services.logs import log_event

router = APIRouter(prefix="/invitations", tags=["invitations"])
admins = require_roles(Role.SUPER_ADMIN, Role.TENANT_ADMIN)


class InviteCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    role: str
    tenant_id: uuid.UUID | None = None


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    tenant_id: uuid.UUID | None
    expires_at: datetime


class InviteCreated(InviteOut):
    email_sent: bool
    # Returned only when the email could not be sent, so the admin can share the link manually.
    invite_url: str | None = None


class InviteInfo(BaseModel):
    email: str
    full_name: str
    role: str
    tenant_name: str | None


class InviteAccept(BaseModel):
    password: str


def _out(inv: Invitation) -> dict:
    return dict(id=inv.id, email=inv.email, full_name=inv.full_name, role=inv.role, tenant_id=inv.tenant_id, expires_at=inv.expires_at)


@router.post("", response_model=InviteCreated, status_code=status.HTTP_201_CREATED)
def create_invitation(body: InviteCreate, request: Request, db: Session = Depends(get_db), actor: User = Depends(admins)) -> InviteCreated:
    email = body.email.lower()
    try:
        rules.check_role_assignment(db, actor, body.role, body.tenant_id)
    except rules.RuleError as e:
        raise HTTPException(e.status, e.message) from None
    if rules.email_in_use(db, email):
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists.")

    inv, token = svc.create(db, email=email, full_name=body.full_name.strip(), role=body.role, tenant_id=body.tenant_id, invited_by=actor.id)
    sent = svc.send(db, inv, token)
    log_event(db, "user.invited", actor=actor, tenant_id=inv.tenant_id, target=email, ip=client_ip(request),
              detail={"role": inv.role, "email_sent": sent})
    return InviteCreated(**_out(inv), email_sent=sent, invite_url=None if sent else svc.invite_url(token))


@router.get("", response_model=list[InviteOut])
def list_invitations(db: Session = Depends(get_db), actor: User = Depends(admins)) -> list[InviteOut]:
    q = select(Invitation).where(Invitation.accepted_at.is_(None)).order_by(Invitation.created_at.desc())
    if actor.role == Role.TENANT_ADMIN.value:
        q = q.where(Invitation.tenant_id == actor.tenant_id)
    return [InviteOut(**_out(i)) for i in db.scalars(q)]


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invitation(invitation_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: User = Depends(admins)) -> None:
    inv = db.get(Invitation, invitation_id)
    if inv is None or (actor.role == Role.TENANT_ADMIN.value and inv.tenant_id != actor.tenant_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invitation not found.")
    db.delete(inv)
    db.commit()
    log_event(db, "user.invitation_revoked", actor=actor, tenant_id=inv.tenant_id, target=inv.email, ip=client_ip(request))


# --- Public endpoints used by the invitee (no session) -------------------------

@router.get("/accept/{token}", response_model=InviteInfo)
def invitation_info(token: str, db: Session = Depends(get_db)) -> InviteInfo:
    inv = svc.find_valid(db, token)
    if inv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This invitation is invalid or has expired.")
    tenant = db.get(Tenant, inv.tenant_id) if inv.tenant_id else None
    return InviteInfo(email=inv.email, full_name=inv.full_name, role=inv.role, tenant_name=tenant.name if tenant else None)


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
    user = svc.accept(db, inv, body.password)
    log_event(db, "user.invitation_accepted", actor=user, ip=client_ip(request))
    return {"email": user.email, "next": "login"}
