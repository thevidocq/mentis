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


def check_role_assignment(db: Session, actor: User, role: str, tenant_id: uuid.UUID | None) -> None:
    """Raise RuleError if `actor` may not create or move a user to (role, tenant_id)."""
    if role not in {r.value for r in Role}:
        raise RuleError(422, "Unknown role.")
    if role == Role.TENANT_ADMIN.value:
        if tenant_id is None:
            raise RuleError(422, "A tenant admin needs a tenant.")
        tenant = db.get(Tenant, tenant_id)
        if tenant is None:
            raise RuleError(404, "Tenant not found.")
        if tenant.is_global:
            raise RuleError(422, "The General tenant is managed by super-admins; it has no tenant admins.")
    elif tenant_id is not None:
        raise RuleError(422, "Only tenant admins belong to a tenant.")

    if actor.role == Role.SUPER_ADMIN.value:
        return
    if actor.role == Role.TENANT_ADMIN.value and role == Role.TENANT_ADMIN.value and tenant_id == actor.tenant_id:
        return
    raise RuleError(403, "Not allowed.")


def can_manage(actor: User, target: User) -> bool:
    if actor.role == Role.SUPER_ADMIN.value:
        return True
    return (
        actor.role == Role.TENANT_ADMIN.value
        and target.role == Role.TENANT_ADMIN.value
        and target.tenant_id == actor.tenant_id
    )


def is_last_super_admin(db: Session, user: User) -> bool:
    if user.role != Role.SUPER_ADMIN.value or not user.is_active:
        return False
    count = db.scalar(
        select(func.count()).select_from(User).where(User.role == Role.SUPER_ADMIN.value, User.is_active.is_(True))
    )
    return count <= 1


def email_in_use(db: Session, email: str) -> bool:
    return db.scalar(select(User.id).where(User.email == email)) is not None
