import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Table, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedMixin, IdMixin


class Role(enum.StrEnum):
    SUPER_ADMIN = "super_admin"    # platform administration
    TENANT_ADMIN = "tenant_admin"  # administers one or more customer tenants
    ANALYST = "analyst"            # chat consultation across all customers


# Customers a tenant admin administers (one or more). Other roles have none.
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
    # Tenant admins only: the customers they administer.
    tenants: Mapped[list["Tenant"]] = relationship(secondary=user_tenants, lazy="selectin", order_by="Tenant.name")  # noqa: F821
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

    @property
    def tenant_ids(self) -> set[uuid.UUID]:
        return {t.id for t in self.tenants}

    def administers(self, tenant_id: uuid.UUID | None) -> bool:
        """Super-admins administer every tenant; tenant admins only their own."""
        if self.role == Role.SUPER_ADMIN.value:
            return True
        return self.role == Role.TENANT_ADMIN.value and tenant_id is not None and tenant_id in self.tenant_ids
