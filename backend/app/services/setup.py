"""Creating the General tenant and the first super-admin (web setup or the create-admin command)."""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password, password_problem
from app.models import Role, Tenant, User
from app.models.base import utcnow

GENERAL_SLUG = "general"


class SetupError(ValueError):
    pass


def needs_setup(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(User)) == 0


def create_first_admin(db: Session, email: str, full_name: str, password: str) -> User:
    """Raises SetupError if a user already exists or the password is weak."""
    if not needs_setup(db):
        raise SetupError("Setup has already been completed.")
    problem = password_problem(password)
    if problem:
        raise SetupError(problem)
    # Creating the General tenant first makes a concurrent second setup fail on its unique slug.
    try:
        if db.scalar(select(Tenant).where(Tenant.slug == GENERAL_SLUG)) is None:
            db.add(Tenant(name="General", slug=GENERAL_SLUG, is_global=True))
            db.flush()
        admin = User(email=email.strip().lower(), full_name=full_name.strip(), password_hash=hash_password(password),
                     role=Role.SUPER_ADMIN.value, password_changed_at=utcnow())
        db.add(admin)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise SetupError("Setup has already been completed.") from None
    return admin
