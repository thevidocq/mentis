"""Login sessions and lockout handling."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_token, new_session_token
from app.models import AuthSession, User
from app.models.base import utcnow


def _aware(dt: datetime) -> datetime:
    # SQLite returns naive datetimes; treat them as UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def create_session(db: Session, user: User, ip: str | None, user_agent: str | None) -> str:
    settings = get_settings()
    token = new_session_token()
    db.add(
        AuthSession(
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=utcnow() + timedelta(hours=settings.session_ttl_hours),
            ip=ip,
            user_agent=(user_agent or "")[:300],
        )
    )
    user.last_login_at = utcnow()
    user.failed_logins = 0
    user.locked_until = None
    db.commit()
    return token


def resolve_session(db: Session, token: str) -> User | None:
    row = db.scalar(select(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    if row is None or _aware(row.expires_at) < utcnow():
        return None
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    return user


def revoke_session(db: Session, token: str) -> None:
    db.execute(delete(AuthSession).where(AuthSession.token_hash == hash_token(token)))
    db.commit()


def revoke_all_sessions(db: Session, user: User) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    db.commit()


def is_locked(user: User) -> bool:
    return user.locked_until is not None and _aware(user.locked_until) > utcnow()


def register_failed_login(db: Session, user: User) -> None:
    settings = get_settings()
    user.failed_logins += 1
    if user.failed_logins >= settings.max_failed_logins:
        user.locked_until = utcnow() + timedelta(minutes=settings.lockout_minutes)
        user.failed_logins = 0
    db.commit()
