"""User management rules shared by the users and invitations routes."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Role, Tenant, User
from app.services import access


class RuleError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


CONTENT_ROLES = {Role.TENANT_ADMIN.value, Role.ANALYST.value}


def resolve_tenants(db: Session, role: str, tenant_ids: list[uuid.UUID] | None, all_tenants: bool) -> list[Tenant]:
    """Validate the tenants for a role. Tenant admins need at least one tenant, all_tenants or the
    General Knowledge Base (which for them means managing it); analysts may have none (they still
    read the GKB); super-admins have none."""
    if role not in {r.value for r in Role}:
        raise RuleError(422, "Unknown role.")
    ids = list(dict.fromkeys(tenant_ids or []))
    if role not in CONTENT_ROLES:
        if ids or all_tenants:
            raise RuleError(422, "Super-admins have no customers: they manage the platform.")
        return []
    if not ids and not all_tenants and role == Role.TENANT_ADMIN.value:
        raise RuleError(422, "Choose at least one customer, all customers, or the General Knowledge Base.")
    tenants = list(db.scalars(select(Tenant).where(Tenant.id.in_(ids)).order_by(Tenant.name))) if ids else []
    if len(tenants) != len(ids):
        raise RuleError(404, "Tenant not found.")
    if role != Role.TENANT_ADMIN.value:
        # Everyone reads the General Knowledge Base: for analysts ticking it means nothing.
        tenants = [t for t in tenants if not t.is_global]
    gkb = [t for t in tenants if t.is_global]
    if all_tenants:
        return gkb  # every customer anyway; only the explicit GKB management is kept
    return tenants


def check_role_assignment(db: Session, actor: User, role: str, tenant_ids: list[uuid.UUID] | None,
                          all_tenants: bool = False) -> list[Tenant]:
    """Raise RuleError if `actor` may not give (role, tenants) to a user. Returns the tenants."""
    tenants = resolve_tenants(db, role, tenant_ids, all_tenants)
    if actor.role == Role.SUPER_ADMIN.value:
        return tenants
    # A tenant admin creates tenant admins and analysts, with only the customers it has itself.
    if role in CONTENT_ROLES and access.covers(db, actor, {t.id for t in tenants}, all_tenants):
        return tenants
    raise RuleError(403, "You can only give customers you have yourself.")


def can_manage(db: Session, actor: User, target: User) -> bool:
    """Super-admins manage everyone. A tenant admin manages tenant admins and analysts whose
    customers it has all (all customers only if it has all customers too)."""
    if actor.role == Role.SUPER_ADMIN.value:
        return True
    if actor.role != Role.TENANT_ADMIN.value or target.role not in CONTENT_ROLES:
        return False
    return access.covers(db, actor, target.tenant_ids, target.all_tenants)


def single_tenant(user: User) -> uuid.UUID | None:
    """The tenant to record in log events: the user's only customer (the GKB aside), else none."""
    ids = {t.id for t in user.tenants if not t.is_global}
    return next(iter(ids)) if len(ids) == 1 and not user.all_tenants else None


def is_last_super_admin(db: Session, user: User) -> bool:
    if user.role != Role.SUPER_ADMIN.value or not user.is_active:
        return False
    count = db.scalar(
        select(func.count()).select_from(User).where(User.role == Role.SUPER_ADMIN.value, User.is_active.is_(True))
    )
    return count <= 1


def email_in_use(db: Session, email: str) -> bool:
    return db.scalar(select(User.id).where(User.email == email)) is not None
