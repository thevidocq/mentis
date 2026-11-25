import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin


class Invitation(IdMixin, CreatedMixin, Base):
    """Email invitation. The link carries a random token; only its hash is stored."""

    __tablename__ = "invitations"

    email: Mapped[str] = mapped_column(String(254), nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # Tenant admins: ids (as strings) of the customers they will administer.
    tenant_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
