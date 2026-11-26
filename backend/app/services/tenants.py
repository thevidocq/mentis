"""Tenant operations."""

import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Invitation, Tenant, User, user_tenants
from app.models.tenant import DEFAULT_TENANT_SETTINGS

ALLOWED_SETTINGS = set(DEFAULT_TENANT_SETTINGS)
STATUSES = {"active", "onboarding", "disabled"}


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug[:56] or "tenant"


def unique_slug(db: Session, name: str) -> str:
    base = slugify(name)
    slug, n = base, 2
    while db.scalar(select(Tenant.id).where(Tenant.slug == slug)) is not None:
        slug, n = f"{base}-{n}", n + 1
    return slug


def name_taken(db: Session, name: str, exclude_id=None) -> bool:
    q = select(Tenant.id).where(func.lower(Tenant.name) == name.lower())
    if exclude_id is not None:
        q = q.where(Tenant.id != exclude_id)
    return db.scalar(q) is not None


def merge_settings(current: dict, changes: dict) -> dict:
    unknown = set(changes) - ALLOWED_SETTINGS
    if unknown:
        raise ValueError(f"Unknown settings: {', '.join(sorted(unknown))}")
    for key, value in changes.items():
        if not isinstance(value, bool):
            raise ValueError(f"Setting {key} must be true or false.")
    return {**DEFAULT_TENANT_SETTINGS, **current, **changes}


def user_count(db: Session, tenant: Tenant) -> int:
    """Users who see this tenant: ticked on their account, or with all customers."""
    ticked = select(user_tenants.c.user_id).where(user_tenants.c.tenant_id == tenant.id)
    return db.scalar(select(func.count()).select_from(User).where(
        User.role.in_(["tenant_admin", "analyst"]), (User.id.in_(ticked)) | User.all_tenants.is_(True))) or 0


def delete_tenant(db: Session, tenant: Tenant) -> None:
    """Remove a customer tenant and everything it owns.

    Documents, versions, pages, chunks and stored files go, and every chat scoped to it.
    Tenant admins of this tenant only are deleted with their chats; admins of other tenants too
    just lose this one. Pending invitations lose it, and are deleted when nothing is left.
    Its integrations (and their encrypted secrets) go too. Log events are kept (retention applies).
    """
    from app.models import Chat, ChatMessage, Integration
    from app.services.versions import delete_tenant_documents

    delete_tenant_documents(db, tenant.id)
    db.execute(delete(Integration).where(Integration.tenant_id == tenant.id))
    admins = list(db.scalars(select(User).where(User.id.in_(select(user_tenants.c.user_id).where(user_tenants.c.tenant_id == tenant.id)))))
    only_here = [u.id for u in admins if u.tenant_ids == {tenant.id}]
    gone = (Chat.scope_tenant_id == tenant.id) | Chat.user_id.in_(only_here)
    db.execute(delete(ChatMessage).where(ChatMessage.chat_id.in_(select(Chat.id).where(gone))))
    db.execute(delete(Chat).where(gone))
    tid = str(tenant.id)
    for inv in db.scalars(select(Invitation).where(Invitation.accepted_at.is_(None))):
        if tid in (inv.tenant_ids or []):
            left = [t for t in inv.tenant_ids if t != tid]
            if left:
                inv.tenant_ids = left
            else:
                db.delete(inv)
    for u in admins:
        if u.id in only_here:
            db.delete(u)
        else:
            u.tenants = [t for t in u.tenants if t.id != tenant.id]
    db.flush()
    tenant_id = tenant.id
    db.delete(tenant)
    db.commit()
    from app.services.versions import cleanup_tenant

    cleanup_tenant(tenant_id)  # files and vector collection, after the rows are gone
