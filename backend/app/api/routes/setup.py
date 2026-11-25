"""First-run setup from the browser. Off by default: the first super-admin is created with

    docker compose exec api python -m app.cli create-admin

so nobody who reaches a freshly installed public address can claim the platform.
Set MENTIS_WEB_SETUP=true to allow the setup page (e.g. a lab reachable only through an SSH tunnel).
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import client_ip
from app.api.schemas import SetupRequest, SetupStatus, UserOut
from app.core.config import get_settings
from app.core.db import get_db
from app.services import setup as svc
from app.services.logs import log_event

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/status", response_model=SetupStatus)
def setup_status(db: Session = Depends(get_db)) -> SetupStatus:
    return SetupStatus(needs_setup=svc.needs_setup(db), web_setup=get_settings().web_setup)


@router.post("", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def run_setup(body: SetupRequest, request: Request, db: Session = Depends(get_db)) -> UserOut:
    if not get_settings().web_setup:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Web setup is off. Create the first super-admin on the server: "
                            "docker compose exec api python -m app.cli create-admin")
    try:
        admin = svc.create_first_admin(db, body.email, body.full_name, body.password)
    except svc.SetupError as e:
        code = status.HTTP_409_CONFLICT if "already" in str(e) else 422
        raise HTTPException(code, str(e)) from None
    log_event(db, "setup.completed", actor=admin, ip=client_ip(request))
    return UserOut.model_validate(admin, from_attributes=True)
