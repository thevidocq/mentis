import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, utcnow


class Chat(IdMixin, CreatedMixin, Base):
    """A conversation. Its customer scope is fixed at creation and never changes."""

    __tablename__ = "chats"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    # NULL = "All customers".
    scope_tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(120), default="New chat", nullable=False)
    title_locked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)  # renamed by the user
    # The General Knowledge Base is searched with the customer unless the user turned it off.
    use_general: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Integrations chosen with # (ids of the scope customer's integrations; empty = none).
    integration_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class ChatMessage(IdMixin, CreatedMixin, Base):
    __tablename__ = "chat_messages"

    chat_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("chats.id", ondelete="CASCADE"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(10), nullable=False)  # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Assistant only:
    status: Mapped[str] = mapped_column(String(12), default="ok", nullable=False)  # ok | not_found | error
    citations: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    followups: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    tenants: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # names the answer refers to
    # Tenant ids whose passages the model read for this answer (cited or not): the answer is hidden
    # from anyone who no longer sees one of them. None for answers saved before 0.6.2.
    searched: Mapped[list | None] = mapped_column(JSON)
    read_documents: Mapped[list | None] = mapped_column(JSON)  # documents whose passages the model read, cited or not
    provider_name: Mapped[str | None] = mapped_column(String(80))
    model: Mapped[str | None] = mapped_column(String(200))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    feedback: Mapped[int | None] = mapped_column(Integer)  # 1 | -1
    # Answer check (services/answer_check): status, issues found by level 1 (values) and level 2 (judge).
    check: Mapped[dict | None] = mapped_column("answer_check", JSON)  # "check" is an SQL keyword
