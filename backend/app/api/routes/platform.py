"""Platform settings for super-admins: SMTP."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.core.db import get_db
from app.models import Role, User
from app.services import mail
from app.services.logs import log_event

router = APIRouter(prefix="/platform", tags=["platform"])
super_admin = require_roles(Role.SUPER_ADMIN)


class SmtpIn(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    security: str | None = None
    username: str | None = Field(default=None, max_length=255)
    # Write-only. Omit to keep the stored password, "" to clear it.
    password: str | None = None
    from_address: EmailStr | None = None


class SmtpTest(BaseModel):
    to: EmailStr


@router.get("/smtp")
def get_smtp(db: Session = Depends(get_db), _: User = Depends(super_admin)) -> dict:
    return mail.public_smtp(mail.get_smtp(db))


@router.put("/smtp")
def put_smtp(body: SmtpIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> dict:
    if body.security is not None and body.security not in mail.SECURITY_MODES:
        raise HTTPException(422, f"Security must be one of: {', '.join(sorted(mail.SECURITY_MODES))}.")
    cfg = mail.save_smtp(db, body.model_dump())
    changed = [k for k, v in body.model_dump().items() if v is not None]
    log_event(db, "platform.smtp_updated", actor=admin, ip=client_ip(request), detail={"fields": changed})
    return mail.public_smtp(cfg)


@router.post("/smtp/test")
def test_smtp(body: SmtpTest, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> dict:
    cfg = mail.get_smtp(db)
    if not mail.is_configured(cfg):
        raise HTTPException(400, "SMTP is not configured.")
    try:
        mail.send_mail(cfg, body.to, "Mentis SMTP test", "SMTP is configured correctly.")
    except Exception as e:  # noqa: BLE001 - report the SMTP error to the admin
        log_event(db, "platform.smtp_test_failed", kind="system", level="error", actor=admin, ip=client_ip(request), detail={"error": str(e)[:300]})
        return {"ok": False, "error": str(e)[:300]}
    log_event(db, "platform.smtp_test_ok", actor=admin, ip=client_ip(request))
    return {"ok": True}
