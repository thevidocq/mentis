import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin


class PasswordReset(IdMixin, CreatedMixin, Base):
    """One-time link to choose a new password. Only the token's hash is stored."""

    __tablename__ = "password_resets"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # None = requested by the user from the sign-in page; else the admin who created the link.
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
