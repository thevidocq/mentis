"""The single Logs section (super-admin only) and syslog forwarding to a SIEM."""

import csv
import io
import json
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.core.db import get_db
from app.models import AuditEvent, Role, Tenant, User
from app.models.base import utcnow
from app.services import syslog
from app.services.logs import log_event

router = APIRouter(tags=["logs"])
super_admin = require_roles(Role.SUPER_ADMIN)
EXPORT_MAX = 100_000
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


class LogOut(BaseModel):
    id: uuid.UUID
    ts: datetime
    kind: str
    level: str
    action: str
    actor_email: str | None
    tenant_id: uuid.UUID | None
    tenant: str | None
    target: str | None
    ip: str | None
    detail: dict


class LogPage(BaseModel):
    items: list[LogOut]
    total: int


class SyslogIn(BaseModel):
    enabled: bool
    host: str = Field(default="", max_length=253)
    port: int = Field(default=514, ge=1, le=65535)
    protocol: str = "udp"
    verify_tls: bool = True
    app_name: str = Field(default="mentis", min_length=1, max_length=48, pattern=r"^[!-~]+$")


def _filtered(kind: str | None, level: str | None, tenant_id: str | None, action: str | None, q: str | None,
              since: datetime | None, until: datetime | None):
    stmt = select(AuditEvent)
    if kind:
        stmt = stmt.where(AuditEvent.kind == kind)
    if level:
        stmt = stmt.where(AuditEvent.level == level)
    if tenant_id == "none":
        stmt = stmt.where(AuditEvent.tenant_id.is_(None))
    elif tenant_id:
        try:
            stmt = stmt.where(AuditEvent.tenant_id == uuid.UUID(tenant_id))
        except ValueError:
            raise HTTPException(422, "Invalid tenant.") from None
    if action:
        stmt = stmt.where(AuditEvent.action.startswith(action))
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(AuditEvent.actor_email.ilike(like), AuditEvent.target.ilike(like),
                              AuditEvent.action.ilike(like), AuditEvent.ip.ilike(like)))
    if since:
        stmt = stmt.where(AuditEvent.ts >= since)
    if until:
        stmt = stmt.where(AuditEvent.ts < until)
    return stmt


def _out(e: AuditEvent, names: dict) -> LogOut:
    return LogOut(id=e.id, ts=e.ts, kind=e.kind, level=e.level, action=e.action, actor_email=e.actor_email,
                  tenant_id=e.tenant_id, tenant=names.get(e.tenant_id) if e.tenant_id else None, target=e.target,
                  ip=e.ip, detail=e.detail or {})


Filters = dict  # the query filters, as keyword arguments for _filtered


def filters(kind: str | None = Query(None, pattern="^(audit|system)$"), level: str | None = Query(None, pattern="^(info|warning|error)$"),
            tenant_id: str | None = None, action: str | None = Query(None, max_length=64), q: str | None = Query(None, max_length=200),
            since: datetime | None = None, until: datetime | None = None) -> Filters:
    return {"kind": kind, "level": level, "tenant_id": tenant_id, "action": action, "q": q, "since": since, "until": until}


@router.get("/logs", response_model=LogPage)
def list_logs(f: Filters = Depends(filters), limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db), _: User = Depends(super_admin)) -> LogPage:
    stmt = _filtered(**f)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(AuditEvent.ts.desc()).limit(limit).offset(offset)).all()
    names = {t.id: t.name for t in db.scalars(select(Tenant))}
    return LogPage(items=[_out(e, names) for e in rows], total=total)


@router.get("/logs/actions", response_model=list[str])
def actions(db: Session = Depends(get_db), _: User = Depends(super_admin)) -> list[str]:
    return list(db.scalars(select(AuditEvent.action).distinct().order_by(AuditEvent.action)))


@router.get("/logs/export")
def export_logs(request: Request, f: Filters = Depends(filters), db: Session = Depends(get_db), admin: User = Depends(super_admin)):
    names = {t.id: t.name for t in db.scalars(select(Tenant))}
    rows = db.scalars(_filtered(**f).order_by(AuditEvent.ts.desc()).limit(EXPORT_MAX)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time_utc", "kind", "level", "action", "actor", "tenant", "target", "ip", "detail"])

    for e in rows:
        cells = [e.ts.isoformat(), e.kind, e.level, e.action, e.actor_email or "", names.get(e.tenant_id, "") if e.tenant_id else "",
                 e.target or "", e.ip or "", json.dumps(e.detail or {}, default=str)]
        # Neutralise spreadsheet formulas in exported text (OWASP: = + - @ and leading tab or carriage return).
        w.writerow([("'" + c) if isinstance(c, str) and c[:1] in FORMULA_START else c for c in cells])
    log_event(db, "logs.exported", actor=admin, ip=client_ip(request), detail={"rows": len(rows)})
    name = f"mentis-logs-{utcnow():%Y%m%d-%H%M}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/logs/summary")
def summary(db: Session = Depends(get_db), _: User = Depends(super_admin)) -> dict:
    """Counts for the last 24 hours, shown above the table."""
    since = utcnow() - timedelta(hours=24)
    rows = db.execute(select(AuditEvent.level, func.count()).where(AuditEvent.ts >= since).group_by(AuditEvent.level)).all()
    return {"since": since, **{lvl: n for lvl, n in rows}}


# --- Syslog --------------------------------------------------------------------

@router.get("/platform/syslog")
def get_syslog(db: Session = Depends(get_db), _: User = Depends(super_admin)) -> dict:
    return {**syslog.get_config(db), "sent": syslog.forwarder.sent, "dropped": syslog.forwarder.dropped,
            "last_error": syslog.forwarder.last_error}


@router.put("/platform/syslog")
def put_syslog(body: SyslogIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> dict:
    if body.protocol not in syslog.PROTOCOLS:
        raise HTTPException(422, "Protocol must be udp, tcp or tls.")
    if body.enabled and not body.host.strip():
        raise HTTPException(422, "Enter the collector host.")
    cfg = syslog.save_config(db, {**body.model_dump(), "host": body.host.strip()})
    log_event(db, "platform.syslog_updated", actor=admin, ip=client_ip(request),
              detail={"enabled": cfg["enabled"], "host": cfg["host"], "port": cfg["port"], "protocol": cfg["protocol"]})
    return cfg


@router.post("/platform/syslog/test")
def test_syslog(db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> dict:
    cfg = syslog.get_config(db)
    if not cfg["host"]:
        return {"ok": False, "error": "Enter and save the collector host first."}
    e = AuditEvent(ts=utcnow(), kind="system", level="info", action="syslog.test", actor_email=admin.email,
                   target="Test message from Mentis", detail={})
    try:
        syslog.send_one(cfg, syslog.format_event(e, cfg.get("app_name") or "mentis"))
    except (OSError, ValueError) as ex:  # ValueError: e.g. UnicodeError for a host name IDNA cannot encode
        return {"ok": False, "error": f"{ex.__class__.__name__}: {ex}"}
    note = " UDP gives no delivery confirmation: check the collector." if cfg["protocol"] == "udp" else ""
    return {"ok": True, "message": f"Test message sent to {cfg['host']}:{cfg['port']} ({cfg['protocol'].upper()}).{note}"}
