"""Password reset: a one-time link, emailed from the sign-in page or created by an admin.

The link only sets a new password. Two-factor authentication is still required to sign in,
every open session is closed and the event is logged.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password, hash_token, new_session_token
from app.models import PasswordReset, User
from app.models.base import utcnow
from app.services import mail, sessions

_log = logging.getLogger("mentis")
RESEND_AFTER = timedelta(minutes=2)  # a new emailed link at most every 2 minutes per user


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def reset_url(token: str) -> str:
    return f"{get_settings().public_url.rstrip('/')}/reset/{token}"


def create(db: Session, user: User, ttl: timedelta, created_by=None) -> str:
    """A new link replaces the user's earlier unused ones."""
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.used_at.is_(None)))
    token = new_session_token()
    db.add(PasswordReset(user_id=user.id, token_hash=hash_token(token), expires_at=utcnow() + ttl, created_by=created_by))
    db.commit()
    return token


def recently_requested(db: Session, user: User) -> bool:
    last = db.scalar(select(PasswordReset.created_at).where(PasswordReset.user_id == user.id, PasswordReset.created_by.is_(None))
                     .order_by(PasswordReset.created_at.desc()).limit(1))
    return last is not None and _aware(last) > utcnow() - RESEND_AFTER


def send(db: Session, user: User, token: str, minutes: int) -> bool:
    cfg = mail.get_smtp(db)
    if not mail.is_configured(cfg):
        return False
    body = (
        f"Hello {user.full_name},\n\n"
        "a new password was requested for your Mentis account.\n\n"
        f"Open this link to choose it (valid for {minutes} minutes, once):\n{reset_url(token)}\n\n"
        "You will still sign in with your authenticator app. If you did not ask for this, ignore this email:\n"
        "your password does not change.\n"
    )
    try:
        mail.send_mail(cfg, user.email, "Reset your Mentis password", body)
        return True
    except Exception as e:  # noqa: BLE001 - the request answers the same either way
        _log.warning("password reset email to %s failed: %s", user.email, e)
        return False


def find_valid(db: Session, token: str) -> tuple[PasswordReset, User] | None:
    row = db.scalar(select(PasswordReset).where(PasswordReset.token_hash == hash_token(token)))
    if row is None or row.used_at is not None or _aware(row.expires_at) < utcnow():
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return row, user


def apply(db: Session, row: PasswordReset, user: User, password: str) -> None:
    user.password_hash = hash_password(password)
    user.password_changed_at = utcnow()
    user.failed_logins, user.locked_until = 0, None
    row.used_at = utcnow()
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id, PasswordReset.id != row.id))
    db.commit()
    sessions.revoke_all_sessions(db, user)
