from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin

DEFAULT_TENANT_SETTINGS = {
    "include_general": True,       # General documentation included in retrieval
    "require_approval": False,     # new document versions go live only after admin approval
    "suggested_followups": True,   # 2-3 follow-up questions under each answer
    "admin_can_set_llm": True,     # tenant admins may choose the tenant's LLM (set by super-admins)
    "chat_passages": None,         # passages read per answer; None = platform default (MENTIS_CHAT_PASSAGES)
}

CHAT_PASSAGES_RANGE = (3, 20)      # fewer misses context, more adds noise and tokens
NUMBER_SETTINGS = {"chat_passages": CHAT_PASSAGES_RANGE}  # integer settings (None = default); the others are true/false

# Settings only super-admins may change.
PLATFORM_SETTINGS = {"admin_can_set_llm"}


class Tenant(IdMixin, CreatedMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Exactly one tenant is global: the General knowledge base. It cannot be deleted.
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_TENANT_SETTINGS), nullable=False)
