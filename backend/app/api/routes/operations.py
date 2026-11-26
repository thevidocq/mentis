"""Retention, LLM usage and configuration import/export."""

import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import client_ip, current_user, require_roles
from app.core.db import get_db
from app.models import Role, User
from app.models.base import utcnow
from app.services import access, config_io, retention
from app.services import usage as usage_svc
from app.services.logs import log_event

router = APIRouter(tags=["operations"])
super_admin = require_roles(Role.SUPER_ADMIN)


class RetentionIn(BaseModel):
    chats_days: int = Field(ge=0, le=retention.MAX_DAYS)
    logs_days: int = Field(ge=0, le=retention.MAX_DAYS)
    versions_keep: int | None = Field(default=None, ge=0, le=retention.MAX_VERSIONS)  # older versions kept per document, 0 = all


@router.get("/platform/retention")
def get_retention(db: Session = Depends(get_db), _: User = Depends(super_admin)) -> dict:
    return retention.get_config(db)


@router.put("/platform/retention")
def put_retention(body: RetentionIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> dict:
    cfg = retention.save_config(db, body.chats_days, body.logs_days, body.versions_keep)
    log_event(db, "platform.retention_updated", actor=admin, ip=client_ip(request), detail=body.model_dump())
    return cfg


@router.post("/platform/retention/purge")
def purge_now(request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> dict:
    result = retention.purge(db)
    log_event(db, "retention.purged", level="warning", actor=admin, ip=client_ip(request), detail=result)
    return result


# --- Usage ---------------------------------------------------------------------

@router.get("/usage")
def get_usage(days: int = Query(30, ge=1, le=3650), since: datetime | None = None, until: datetime | None = None,
              db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    """Super-admins: every customer. Tenant admins: their own customer only."""
    if user.role == Role.ANALYST.value:
        raise HTTPException(403, "Not allowed for your role.")
    until = until or utcnow()
    since = since or until - timedelta(days=days)
    own = {t.id for t in access.managed(db, user)} if user.role == Role.TENANT_ADMIN.value else None
    data = usage_svc.usage(db, since, until, tenant_ids=own)
    if own is not None:  # prices and costs are the platform's business
        for r in data["rows"]:
            r["cost_usd"] = None
        data["totals"]["cost_usd"] = None
    return {"since": since, "until": until, **data}


# --- Configuration import/export -----------------------------------------------

@router.get("/platform/config/export")
def export_config(request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> Response:
    data = config_io.export_config(db)
    log_event(db, "config.exported", actor=admin, ip=client_ip(request))
    name = f"mentis-config-{utcnow():%Y%m%d-%H%M}.json"
    return Response(json.dumps(data, indent=2, default=str), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/platform/config/import")
async def import_config(request: Request, file: UploadFile = File(...), apply: bool = Query(False),
                        db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> dict:
    raw = await file.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(413, "The file is larger than 2 MB.")
    try:
        data = json.loads(raw)
        plan = config_io.import_config(db, data, apply=apply)
    except (ValueError, KeyError, TypeError) as e:
        db.rollback()
        raise HTTPException(422, str(e) if isinstance(e, config_io.ImportError_) else "Invalid configuration file.") from None
    if apply:
        log_event(db, "config.imported", level="warning", actor=admin, ip=client_ip(request), detail={"changes": len(plan)})
    return {"applied": apply, "changes": plan}
