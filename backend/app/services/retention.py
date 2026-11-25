"""How long chats and log events are kept, and the purge that enforces it.

0 days = keep forever. The worker runs the purge once a day; the super-admin can run it now.
"""

from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Chat, ChatMessage, PlatformSetting
from app.models.base import utcnow

KEY = "retention"
DEFAULTS = {"chats_days": 365, "logs_days": 365, "last_purge": None, "last_result": None}
MAX_DAYS = 3650


def get_config(db: Session) -> dict:
    row = db.get(PlatformSetting, KEY)
    return {**DEFAULTS, **(row.value if row else {})}


def _store(db: Session, cfg: dict) -> None:
    row = db.get(PlatformSetting, KEY)
    if row is None:
        db.add(PlatformSetting(key=KEY, value=cfg))
    else:
        row.value = dict(cfg)


def save_config(db: Session, chats_days: int, logs_days: int) -> dict:
    cfg = {**get_config(db), "chats_days": chats_days, "logs_days": logs_days}
    _store(db, cfg)
    db.commit()
    return cfg


def purge(db: Session) -> dict:
    """Delete chats not updated and log events older than the configured periods."""
    cfg = get_config(db)
    now = utcnow()
    result = {"chats": 0, "messages": 0, "log_events": 0}
    if cfg["chats_days"]:
        cutoff = now - timedelta(days=cfg["chats_days"])
        old = select(Chat.id).where(Chat.updated_at < cutoff)
        result["messages"] = db.execute(delete(ChatMessage).where(ChatMessage.chat_id.in_(old))).rowcount or 0
        result["chats"] = db.execute(delete(Chat).where(Chat.updated_at < cutoff)).rowcount or 0
    if cfg["logs_days"]:
        cutoff = now - timedelta(days=cfg["logs_days"])
        result["log_events"] = db.execute(delete(AuditEvent).where(AuditEvent.ts < cutoff)).rowcount or 0
    cfg["last_purge"], cfg["last_result"] = now.isoformat(), result
    _store(db, cfg)
    db.commit()
    return result
