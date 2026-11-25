import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin


class Role(enum.StrEnum):
    SUPER_ADMIN = "super_admin"    # platform administration
    TENANT_ADMIN = "tenant_admin"  # administers exactly one customer tenant
    ANALYST = "analyst"            # chat consultation across all customers


class User(IdMixin, CreatedMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # Set only for tenant admins.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # TOTP secret, encrypted with app.core.crypto. 2FA is mandatory: enabled at first login.
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Per-user UI preferences, e.g. {"theme": "dark"}.
    preferences: Mapped[dict] = mapped_column(JSON, default=lambda: {"theme": "dark"}, nullable=False)
