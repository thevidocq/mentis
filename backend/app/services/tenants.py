"""Tenant operations."""

import re

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models import Invitation, Tenant, User
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
    return db.scalar(select(func.count()).select_from(User).where(User.tenant_id == tenant.id)) or 0


def delete_tenant(db: Session, tenant: Tenant) -> None:
    """Remove a customer tenant and everything it owns.

    Documents, versions, pages, chunks and stored files are removed here. Later blocks add
    the Qdrant collection, chats and integrations.
    Log events are kept (retention applies).
    """
    from app.services.versions import delete_tenant_documents

    delete_tenant_documents(db, tenant.id)
    db.execute(delete(Invitation).where(Invitation.tenant_id == tenant.id))
    db.execute(delete(User).where(User.tenant_id == tenant.id))
    db.delete(tenant)
    db.commit()
