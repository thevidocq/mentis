"""Who can see which tenant. The single place for tenant access rules.

- Super-admins manage the platform and see no customer content: no tenants here.
- Tenant admins and analysts see the tenants ticked for them, or every tenant (present and
  future) with all_tenants. General is a tenant like the others, ticked by default.
- Tenant admins administer (documents, settings, LLM, users) the tenants they see.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Role, Tenant, User

CONTENT_ROLES = {Role.TENANT_ADMIN.value, Role.ANALYST.value}


def tenants(db: Session, user: User) -> list[Tenant]:
    """Tenants the user can see, sorted with General first."""
    if user.role not in CONTENT_ROLES:
        return []
    rows = list(db.scalars(select(Tenant))) if user.all_tenants else list(user.tenants)
    return sorted(rows, key=lambda t: (not t.is_global, t.name.lower()))


def tenant_ids(db: Session, user: User) -> set[uuid.UUID]:
    return {t.id for t in tenants(db, user)}


def sees(db: Session, user: User, tenant_id: uuid.UUID | None) -> bool:
    if tenant_id is None or user.role not in CONTENT_ROLES:
        return False
    return user.all_tenants or tenant_id in user.tenant_ids


def administers(db: Session, user: User, tenant_id: uuid.UUID | None) -> bool:
    """Documents and tenant settings: tenant admins of that tenant only (never super-admins)."""
    return user.role == Role.TENANT_ADMIN.value and sees(db, user, tenant_id)


def general(db: Session) -> Tenant | None:
    return db.scalar(select(Tenant).where(Tenant.is_global.is_(True)))


def covers(db: Session, actor: User, ids: set[uuid.UUID], all_tenants: bool) -> bool:
    """True if `actor` may hand out these tenants: only what it has itself."""
    if actor.role == Role.SUPER_ADMIN.value:
        return True
    if actor.role != Role.TENANT_ADMIN.value:
        return False
    if all_tenants:
        return actor.all_tenants
    return actor.all_tenants or ids <= actor.tenant_ids
