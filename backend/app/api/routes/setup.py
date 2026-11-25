"""First-run setup: creates the General tenant and the first super-admin, once."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.api.schemas import SetupRequest, SetupStatus, UserOut
from app.core.db import get_db
from app.core.security import hash_password, password_problem
from app.models import Role, Tenant, User
from app.models.base import utcnow
from app.services.logs import log_event

router = APIRouter(prefix="/setup", tags=["setup"])

GENERAL_SLUG = "general"


def _needs_setup(db: Session) -> bool:
    return db.scalar(select(func.count()).select_from(User)) == 0


@router.get("/status", response_model=SetupStatus)
def setup_status(db: Session = Depends(get_db)) -> SetupStatus:
    return SetupStatus(needs_setup=_needs_setup(db))


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def run_setup(body: SetupRequest, request: Request, db: Session = Depends(get_db)) -> UserOut:
    if not _needs_setup(db):
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup has already been completed.")
    problem = password_problem(body.password)
    if problem:
        raise HTTPException(422, problem)

    # Creating the General tenant first makes a concurrent second setup fail on its unique slug.
    general = db.scalar(select(Tenant).where(Tenant.slug == GENERAL_SLUG))
    try:
        if general is None:
            db.add(Tenant(name="General", slug=GENERAL_SLUG, is_global=True))
            db.flush()
        admin = User(
            email=body.email.lower(),
            full_name=body.full_name.strip(),
            password_hash=hash_password(body.password),
            role=Role.SUPER_ADMIN.value,
            password_changed_at=utcnow(),
        )
        db.add(admin)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Setup has already been completed.") from None

    log_event(db, "setup.completed", actor=admin, ip=client_ip(request))
    return UserOut.model_validate(admin, from_attributes=True)
