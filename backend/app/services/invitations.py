"""Invitations: create, send, accept."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, hash_token, new_session_token
from app.models import Invitation, Tenant, User
from app.models.base import utcnow
from app.services import mail

_log = logging.getLogger("mentis")

ROLE_LABELS = {"super_admin": "super-admin", "tenant_admin": "tenant admin", "analyst": "analyst"}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def invite_url(token: str) -> str:
    return f"{get_settings().public_url.rstrip('/')}/invite/{token}"


def create(db: Session, *, email: str, full_name: str, role: str, tenant_ids: list[str], all_tenants: bool = False, invited_by) -> tuple[Invitation, str]:
    # A new invitation replaces any pending one for the same email.
    db.execute(delete(Invitation).where(Invitation.email == email, Invitation.accepted_at.is_(None)))
    token = new_session_token()
    inv = Invitation(
        email=email,
        full_name=full_name,
        role=role,
        tenant_ids=tenant_ids,
        all_tenants=all_tenants,
        token_hash=hash_token(token),
        expires_at=utcnow() + timedelta(hours=get_settings().invitation_ttl_hours),
        invited_by=invited_by,
    )
    db.add(inv)
    db.commit()
    return inv, token


def send(db: Session, inv: Invitation, token: str) -> bool:
    """Email the invitation. Returns False if SMTP is not configured or sending fails."""
    cfg = mail.get_smtp(db)
    if not mail.is_configured(cfg):
        return False
    names = _tenant_names(db, inv)
    scope = " for all customers" if inv.all_tenants else (f" for {', '.join(names)}" if names else "")
    body = (
        f"Hello {inv.full_name},\n\n"
        f"you have been invited to Mentis as {ROLE_LABELS.get(inv.role, inv.role)}{scope}.\n\n"
        f"Open this link to set your password (valid for {get_settings().invitation_ttl_hours} hours):\n"
        f"{invite_url(token)}\n\n"
        "At your first login you will set up an authenticator app (two-factor authentication).\n"
    )
    try:
        mail.send_mail(cfg, inv.email, "Your Mentis invitation", body)
        return True
    except Exception as e:  # noqa: BLE001 - any SMTP failure falls back to the manual link
        _log.warning("invitation email to %s failed: %s", inv.email, e)
        return False


def find_valid(db: Session, token: str) -> Invitation | None:
    inv = db.scalar(select(Invitation).where(Invitation.token_hash == hash_token(token)))
    if inv is None or inv.accepted_at is not None or _aware(inv.expires_at) < utcnow():
        return None
    return inv


def _tenants(db: Session, inv: Invitation) -> list[Tenant]:
    ids = [uuid.UUID(t) for t in inv.tenant_ids or []]
    return list(db.scalars(select(Tenant).where(Tenant.id.in_(ids)).order_by(Tenant.name))) if ids else []


def tenants_of(db: Session, inv: Invitation) -> list[Tenant]:
    return _tenants(db, inv)


def _tenant_names(db: Session, inv: Invitation) -> list[str]:
    return [t.name for t in _tenants(db, inv)]


def accept(db: Session, inv: Invitation, password: str) -> User:
    user = User(
        email=inv.email,
        full_name=inv.full_name,
        password_hash=hash_password(password),
        role=inv.role,
        password_changed_at=utcnow(),
    )
    # Tenants deleted since the invitation are simply skipped.
    user.tenants = _tenants(db, inv)
    user.all_tenants = inv.all_tenants
    db.add(user)
    inv.accepted_at = utcnow()
    db.commit()
    return user
