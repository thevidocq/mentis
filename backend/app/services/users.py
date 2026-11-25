"""User management rules shared by the users and invitations routes."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Role, Tenant, User


class RuleError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def resolve_tenants(db: Session, role: str, tenant_ids: list[uuid.UUID] | None) -> list[Tenant]:
    """Validate the tenants for a role. Tenant admins need at least one customer tenant; others none."""
    if role not in {r.value for r in Role}:
        raise RuleError(422, "Unknown role.")
    ids = list(dict.fromkeys(tenant_ids or []))
    if role != Role.TENANT_ADMIN.value:
        if ids:
            raise RuleError(422, "Only tenant admins belong to tenants.")
        return []
    if not ids:
        raise RuleError(422, "A tenant admin needs at least one tenant.")
    tenants = list(db.scalars(select(Tenant).where(Tenant.id.in_(ids))))
    if len(tenants) != len(ids):
        raise RuleError(404, "Tenant not found.")
    if any(t.is_global for t in tenants):
        raise RuleError(422, "The General tenant is managed by super-admins; it has no tenant admins.")
    return tenants


def check_role_assignment(db: Session, actor: User, role: str, tenant_ids: list[uuid.UUID] | None) -> list[Tenant]:
    """Raise RuleError if `actor` may not create or move a user to (role, tenants). Returns the tenants."""
    tenants = resolve_tenants(db, role, tenant_ids)
    if actor.role == Role.SUPER_ADMIN.value:
        return tenants
    # A tenant admin may only give its own tenants to other tenant admins.
    if actor.role == Role.TENANT_ADMIN.value and role == Role.TENANT_ADMIN.value and {t.id for t in tenants} <= actor.tenant_ids:
        return tenants
    raise RuleError(403, "Not allowed.")


def can_manage(actor: User, target: User) -> bool:
    """Super-admins manage everyone. A tenant admin manages tenant admins whose tenants are all its own."""
    if actor.role == Role.SUPER_ADMIN.value:
        return True
    return (
        actor.role == Role.TENANT_ADMIN.value
        and target.role == Role.TENANT_ADMIN.value
        and bool(target.tenant_ids)
        and target.tenant_ids <= actor.tenant_ids
    )


def single_tenant(user: User) -> uuid.UUID | None:
    """The tenant to record in log events: the user's only tenant, else none."""
    ids = user.tenant_ids
    return next(iter(ids)) if len(ids) == 1 else None


def is_last_super_admin(db: Session, user: User) -> bool:
    if user.role != Role.SUPER_ADMIN.value or not user.is_active:
        return False
    count = db.scalar(
        select(func.count()).select_from(User).where(User.role == Role.SUPER_ADMIN.value, User.is_active.is_(True))
    )
    return count <= 1


def email_in_use(db: Session, email: str) -> bool:
    return db.scalar(select(User.id).where(User.email == email)) is not None
