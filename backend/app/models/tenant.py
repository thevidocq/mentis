from sqlalchemy import JSON, Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin

DEFAULT_TENANT_SETTINGS = {
    "include_general": True,       # General documentation included in retrieval
    "require_approval": False,     # new document versions go live only after admin approval
    "suggested_followups": True,   # 2-3 follow-up questions under each answer
}


class Tenant(IdMixin, CreatedMixin, Base):
    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Exactly one tenant is global: the General knowledge base. It cannot be deleted.
    is_global: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    settings: Mapped[dict] = mapped_column(JSON, default=lambda: dict(DEFAULT_TENANT_SETTINGS), nullable=False)
