import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, utcnow


class Integration(IdMixin, CreatedMixin, Base):
    """An instance of a connector plugin configured for one customer (e.g. its ServiceNow).

    Read-only by contract. Secrets (passwords, API keys, client secrets) are one encrypted JSON
    object and never leave the API in clear text.
    """

    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_integrations_tenant_name"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    plugin: Mapped[str] = mapped_column(String(64), nullable=False)   # entry point name, e.g. "servicenow"
    name: Mapped[str] = mapped_column(String(80), nullable=False)     # shown after # in the chat
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    secrets_enc: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
