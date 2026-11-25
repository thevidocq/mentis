import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, IdMixin, utcnow


class AuditEvent(IdMixin, Base):
    """One row of the single Logs section: audit events (who did what) and system events.

    Chat content is never stored here: chat events carry metadata only (who, when, which tenant).
    """

    __tablename__ = "log_events"

    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)    # "audit" | "system"
    level: Mapped[str] = mapped_column(String(10), default="info", nullable=False)  # info | warning | error
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)   # e.g. auth.login.success
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    actor_email: Mapped[str | None] = mapped_column(String(254))
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    target: Mapped[str | None] = mapped_column(String(200))
    ip: Mapped[str | None] = mapped_column(String(64))
    detail: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
