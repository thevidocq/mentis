"""Forgotten password: request a link from the sign-in page, set the new password, admin-created links."""

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import password_problem
from app.models import Role, User
from app.services import password_reset as svc
from app.services import users as rules
from app.services.logs import log_event

router = APIRouter(tags=["password reset"])
admins = require_roles(Role.SUPER_ADMIN, Role.TENANT_ADMIN)

SENT = "If an account exists for this email, a link to reset the password has been sent."


class ForgotIn(BaseModel):
    email: EmailStr


class ResetIn(BaseModel):
    password: str


class ResetInfo(BaseModel):
    email: str


class AdminLinkOut(BaseModel):
    email_sent: bool
    reset_url: str | None = None  # only when it could not be emailed
    expires_hours: int


@router.post("/auth/password/forgot", status_code=status.HTTP_202_ACCEPTED)
def forgot(body: ForgotIn, request: Request, db: Session = Depends(get_db)) -> dict:
    """Same answer whether or not the email exists, so it cannot be used to find accounts."""
    email = body.email.lower()
    user = db.scalar(select(User).where(User.email == email))
    ip = client_ip(request)
    if user is None or not user.is_active:
        log_event(db, "auth.password.reset_requested", level="warning", actor_email=email, ip=ip, detail={"sent": False, "reason": "no_active_user"})
        return {"detail": SENT}
    if svc.recently_requested(db, user):
        log_event(db, "auth.password.reset_requested", level="warning", actor=user, ip=ip, detail={"sent": False, "reason": "too_soon"})
        return {"detail": SENT}
    minutes = get_settings().password_reset_ttl_minutes
    token = svc.create(db, user, timedelta(minutes=minutes))
    sent = svc.send(db, user, token, minutes)
    log_event(db, "auth.password.reset_requested", actor=user, ip=ip, detail={"sent": sent})
    return {"detail": SENT}


@router.get("/auth/password/reset/{token}", response_model=ResetInfo)
def reset_info(token: str, db: Session = Depends(get_db)) -> ResetInfo:
    found = svc.find_valid(db, token)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link is invalid, already used or expired. Ask for a new one.")
    return ResetInfo(email=found[1].email)


@router.post("/auth/password/reset/{token}", status_code=status.HTTP_204_NO_CONTENT)
def reset(token: str, body: ResetIn, request: Request, db: Session = Depends(get_db)) -> None:
    found = svc.find_valid(db, token)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This link is invalid, already used or expired. Ask for a new one.")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(422, problem)
    row, user = found
    svc.apply(db, row, user, body.password)
    log_event(db, "auth.password.reset", level="warning", actor=user, ip=client_ip(request),
              detail={"by_admin": row.created_by is not None})


@router.post("/users/{user_id}/password-reset", response_model=AdminLinkOut)
def admin_link(user_id: uuid.UUID, request: Request, db: Session = Depends(get_db), actor: User = Depends(admins)) -> AdminLinkOut:
    """For a user who lost the password: emailed when SMTP works, otherwise shown to share by hand."""
    target = db.get(User, user_id)
    if target is None or not rules.can_manage(db, actor, target):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found.")
    if target.id == actor.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Change your own password from your account page.")
    if not target.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "The account is disabled. Enable it first.")
    hours = get_settings().password_reset_admin_ttl_hours
    token = svc.create(db, target, timedelta(hours=hours), created_by=actor.id)
    sent = svc.send(db, target, token, hours * 60)
    log_event(db, "user.password_reset_link", level="warning", actor=actor, tenant_id=rules.single_tenant(target),
              target=target.email, ip=client_ip(request), detail={"email_sent": sent})
    return AdminLinkOut(email_sent=sent, reset_url=None if sent else svc.reset_url(token), expires_hours=hours)
