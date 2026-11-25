import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedMixin, IdMixin


class Role(enum.StrEnum):
    SUPER_ADMIN = "super_admin"    # platform administration
    TENANT_ADMIN = "tenant_admin"  # administers the customers assigned to it
    ANALYST = "analyst"            # chat consultation on the customers assigned to it


# Customers assigned to a tenant admin or an analyst. Super-admins have none: they see no content.
user_tenants = Table(
    "user_tenants",
    Base.metadata,
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("tenant_id", Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True, index=True),
)


class User(IdMixin, CreatedMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # Tenant admins and analysts: the customers assigned (General included by default).
    tenants: Mapped[list["Tenant"]] = relationship(secondary=user_tenants, lazy="selectin", order_by="Tenant.name")  # noqa: F821
    # "All customers, including future ones": every tenant, now and later, without ticking them.
    all_tenants: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # TOTP secret, encrypted with app.core.crypto. 2FA is mandatory: enabled at first login.
    totp_secret_enc: Mapped[str | None] = mapped_column(Text)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Last TOTP time step accepted: an older or equal step is a replayed code.
    totp_last_step: Mapped[int | None] = mapped_column(Integer)

    failed_logins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Per-user UI preferences, e.g. {"theme": "dark"}.
    preferences: Mapped[dict] = mapped_column(JSON, default=lambda: {"theme": "dark"}, nullable=False)

    @property
    def tenant_ids(self) -> set[uuid.UUID]:
        """The tenants ticked for this user (not expanded for all_tenants: see access.tenant_ids)."""
        return {t.id for t in self.tenants}
