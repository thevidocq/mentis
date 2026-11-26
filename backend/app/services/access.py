"""Who can see which tenant. The single place for tenant access rules.

- Super-admins manage the platform and see no customer content: no tenants here.
- Tenant admins and analysts see the customers ticked for them, or every customer (present and
  future) with all_tenants.
- The General Knowledge Base (the tenant with is_global) holds general knowledge only, no customer
  context: every tenant admin and analyst reads it (chat). Only tenant admins with it ticked
  explicitly manage it; all_tenants does not include managing it.
- Tenant admins administer (documents, settings, LLM, users) the customers they see.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Role, Tenant, User

CONTENT_ROLES = {Role.TENANT_ADMIN.value, Role.ANALYST.value}


def _sorted(rows) -> list[Tenant]:
    return sorted(rows, key=lambda t: (not t.is_global, t.name.lower()))


def tenants(db: Session, user: User) -> list[Tenant]:
    """Tenants the user can read (chat): its customers plus the General Knowledge Base, GKB first."""
    if user.role not in CONTENT_ROLES:
        return []
    rows = list(db.scalars(select(Tenant))) if user.all_tenants else list(user.tenants)
    gkb = general(db)
    if gkb is not None and gkb not in rows:
        rows.append(gkb)
    return _sorted(rows)


def manages_general(user: User) -> bool:
    """Tenant admins with the General Knowledge Base ticked explicitly."""
    return user.role == Role.TENANT_ADMIN.value and any(t.is_global for t in user.tenants)


def managed(db: Session, user: User) -> list[Tenant]:
    """Tenants a tenant admin administers: its customers, plus the GKB only when ticked for it."""
    if user.role != Role.TENANT_ADMIN.value:
        return []
    return [t for t in tenants(db, user) if not t.is_global or manages_general(user)]


def tenant_ids(db: Session, user: User) -> set[uuid.UUID]:
    return {t.id for t in tenants(db, user)}


def _is_general(db: Session, tenant_id: uuid.UUID) -> bool:
    gkb = general(db)
    return gkb is not None and gkb.id == tenant_id


def sees(db: Session, user: User, tenant_id: uuid.UUID | None) -> bool:
    """Read access: the user's customers, and the General Knowledge Base for everyone."""
    if tenant_id is None or user.role not in CONTENT_ROLES:
        return False
    return user.all_tenants or tenant_id in user.tenant_ids or _is_general(db, tenant_id)


def administers(db: Session, user: User, tenant_id: uuid.UUID | None) -> bool:
    """Documents and tenant settings: tenant admins of that tenant only (never super-admins).
    The General Knowledge Base only for tenant admins who have it ticked explicitly."""
    if user.role != Role.TENANT_ADMIN.value or tenant_id is None:
        return False
    if _is_general(db, tenant_id):
        return manages_general(user)
    return user.all_tenants or tenant_id in user.tenant_ids


def general(db: Session) -> Tenant | None:
    return db.scalar(select(Tenant).where(Tenant.is_global.is_(True)))


def covers(db: Session, actor: User, ids: set[uuid.UUID], all_tenants: bool) -> bool:
    """True if `actor` may hand out these tenants: only what it has itself."""
    if actor.role == Role.SUPER_ADMIN.value:
        return True
    if actor.role != Role.TENANT_ADMIN.value:
        return False
    gkb = general(db)
    if gkb is not None and gkb.id in ids:
        # Managing the General Knowledge Base is handed out only by those who manage it.
        if not manages_general(actor):
            return False
        ids = ids - {gkb.id}
    if all_tenants:
        return actor.all_tenants
    return actor.all_tenants or ids <= actor.tenant_ids
