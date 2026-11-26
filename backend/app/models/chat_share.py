import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin


class ChatShare(IdMixin, CreatedMixin, Base):
    """A read-only link to a chat, for colleagues signed in to Mentis. Only the token's hash is stored."""

    __tablename__ = "chat_shares"

    chat_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
