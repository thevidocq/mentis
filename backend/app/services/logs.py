"""Writes events to the single Logs section (audit + system)."""

import logging
import uuid

from sqlalchemy.orm import Session

from app.models import AuditEvent, User

_log = logging.getLogger("mentis")


def log_event(
    db: Session,
    action: str,
    *,
    kind: str = "audit",
    level: str = "info",
    actor: User | None = None,
    actor_email: str | None = None,
    tenant_id: uuid.UUID | None = None,
    target: str | None = None,
    ip: str | None = None,
    detail: dict | None = None,
    commit: bool = True,
) -> AuditEvent:
    event = AuditEvent(
        kind=kind,
        level=level,
        action=action,
        actor_user_id=actor.id if actor else None,
        actor_email=actor.email if actor else actor_email,
        tenant_id=tenant_id if tenant_id is not None else (actor.tenant_id if actor else None),
        target=target,
        ip=ip,
        detail=detail or {},
    )
    db.add(event)
    if commit:
        db.commit()
    # Mirror to stdout so `docker compose logs` shows it; syslog forwarding hooks in here later.
    _log.info("%s %s actor=%s target=%s", kind, action, event.actor_email, target)
    return event
