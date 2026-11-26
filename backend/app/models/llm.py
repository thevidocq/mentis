from sqlalchemy import JSON, Boolean, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin


class LlmProvider(IdMixin, CreatedMixin, Base):
    """An LLM endpoint configured by the super-admin; tenants pick one (and a fallback)."""

    __tablename__ = "llm_providers"

    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)  # shown in the LLM badge
    # anthropic | openai_chat | openai_responses
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key_enc: Mapped[str | None] = mapped_column(Text)
    # e.g. {"reasoning_effort": "medium", "max_tokens": 1500}
    options: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    # answers: writes the answers; checker: checks them against the sources (one default per role).
    role: Mapped[str] = mapped_column(String(12), default="answers", server_default="answers", nullable=False)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
