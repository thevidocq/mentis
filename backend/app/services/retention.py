"""How long chats, log events and old document versions are kept, and the purge that enforces it.

0 = keep forever (all versions). The worker runs the purge once a day; the super-admin can run it now.
The purge also runs the storage sweep (files and vectors left by deletions while MinIO or Qdrant
were down).
"""

import logging
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (
    Approval,
    AuditEvent,
    DocumentVersion,
    VersionStatus,
    AuthSession,
    Chat,
    ChatMessage,
    ChatShare,
    Invitation,
    PasswordReset,
    PlatformSetting,
)
from app.models.base import utcnow
from app.services import storage_sweep, versions

_log = logging.getLogger("mentis.retention")

KEY = "retention"
DEFAULTS = {"chats_days": 365, "logs_days": 365, "versions_keep": 0, "last_purge": None, "last_result": None}
MAX_DAYS = 3650
MAX_VERSIONS = 100


def get_config(db: Session) -> dict:
    row = db.get(PlatformSetting, KEY)
    return {**DEFAULTS, **(row.value if row else {})}


def _store(db: Session, cfg: dict) -> None:
    row = db.get(PlatformSetting, KEY)
    if row is None:
        db.add(PlatformSetting(key=KEY, value=cfg))
    else:
        row.value = dict(cfg)


def save_config(db: Session, chats_days: int, logs_days: int, versions_keep: int | None = None) -> dict:
    cfg = {**get_config(db), "chats_days": chats_days, "logs_days": logs_days}
    if versions_keep is not None:
        cfg["versions_keep"] = versions_keep
    _store(db, cfg)
    db.commit()
    return cfg


def purge(db: Session) -> dict:
    """Delete chats not updated and log events older than the configured periods."""
    cfg = get_config(db)
    now = utcnow()
    result = {"chats": 0, "messages": 0, "log_events": 0, "versions": 0}
    if cfg["chats_days"]:
        cutoff = now - timedelta(days=cfg["chats_days"])
        old = select(Chat.id).where(Chat.updated_at < cutoff)
        db.execute(delete(ChatShare).where(ChatShare.chat_id.in_(old)))
        result["messages"] = db.execute(delete(ChatMessage).where(ChatMessage.chat_id.in_(old))).rowcount or 0
        result["chats"] = db.execute(delete(Chat).where(Chat.updated_at < cutoff)).rowcount or 0
    if cfg["logs_days"]:
        cutoff = now - timedelta(days=cfg["logs_days"])
        result["log_events"] = db.execute(delete(AuditEvent).where(AuditEvent.ts < cutoff)).rowcount or 0
    # Housekeeping, whatever the settings: expired sign-in sessions and invitations expired for a week.
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now))
    db.execute(delete(Invitation).where(Invitation.accepted_at.is_(None), Invitation.expires_at < now - timedelta(days=7)))
    db.execute(delete(PasswordReset).where(PasswordReset.expires_at < now - timedelta(days=7)))
    db.execute(delete(ChatShare).where(ChatShare.expires_at < now - timedelta(days=7)))
    db.commit()
    if cfg.get("versions_keep"):
        result["versions"] = _purge_versions(db, int(cfg["versions_keep"]))
    try:
        result.update({f"orphan_{k}": v for k, v in storage_sweep.sweep(db).items()})
    except Exception:  # noqa: BLE001 - storage down: the rest of the purge still counts
        _log.warning("storage sweep failed", exc_info=True)
    cfg = get_config(db)
    cfg["last_purge"], cfg["last_result"] = now.isoformat(), result
    _store(db, cfg)
    db.commit()
    return result


def _purge_versions(db: Session, keep: int) -> int:
    """Per document, keep the version in use, the latest one and `keep` older versions; delete the
    rest with their files and vectors. Versions waiting approval or still processing are kept."""
    old: list[DocumentVersion] = []
    by_doc: dict = {}
    for v in db.scalars(select(DocumentVersion).order_by(DocumentVersion.document_id, DocumentVersion.version.desc())):
        by_doc.setdefault(v.document_id, []).append(v)
    for vs in by_doc.values():
        older = [v for v in vs[1:] if not v.is_active and v.approval != Approval.PENDING
                 and v.status in (VersionStatus.READY, VersionStatus.FAILED)]
        old.extend(older[keep:])
    if old:
        versions.delete_versions(db, old)
    return len(old)
