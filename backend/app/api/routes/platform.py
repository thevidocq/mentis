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


class EmbeddingIn(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    model: str | None = Field(default=None, max_length=200)
    # Write-only. Omit to keep, "" to clear.
    api_key: str | None = None


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


@router.get("/status")
def platform_status(db: Session = Depends(get_db), _: User = Depends(super_admin)) -> dict:
    """Health of each service, for the Service status page."""
    import time

    from sqlalchemy import text

    from app import __version__
    from app.services import jobs, storage

    def timed(fn):
        t0 = time.perf_counter()
        try:
            ok = bool(fn())
        except Exception:  # noqa: BLE001 - a failing check means the service is down
            ok = False
        return ok, round((time.perf_counter() - t0) * 1000)

    from app.services import embeddings, vector_index

    db_ok, db_ms = timed(lambda: db.execute(text("SELECT 1")) is not None)
    st_ok, st_ms = timed(lambda: storage.get_storage().ping())
    q = jobs.queue_health()
    vx_ok, vx_ms = timed(lambda: vector_index.client().get_collections() is not None)
    cfg = embeddings.get_config(db)
    em_ok, em_ms = timed(lambda: len(embeddings.embed(cfg, ["health check"])[0]) > 0)
    services = [
        {"name": "API backend", "category": "Core", "state": "ok", "latency_ms": None, "detail": f"v{__version__}"},
        {"name": "PostgreSQL", "category": "Data", "state": "ok" if db_ok else "down", "latency_ms": db_ms, "detail": ""},
        {"name": "MinIO (documents)", "category": "Data", "state": "ok" if st_ok else "down", "latency_ms": st_ms, "detail": ""},
        {"name": "Redis (job queue)", "category": "Data", "state": "ok" if q["redis"] else "down", "latency_ms": None,
         "detail": f"{q['queued']} jobs waiting" if q["redis"] else ""},
        {"name": "Ingestion worker", "category": "Core", "state": "ok" if q["workers"] else "down", "latency_ms": None,
         "detail": f"{q['workers']} running" if q["workers"] else "no worker listening"},
        {"name": "Qdrant (vector index)", "category": "AI", "state": "ok" if vx_ok else "down", "latency_ms": vx_ms, "detail": ""},
        {"name": "Embeddings", "category": "AI", "state": "ok" if em_ok else "down", "latency_ms": em_ms,
         "detail": cfg["model"] if em_ok else f"not reachable at {cfg['url']}"},
    ]
    services.extend(_llm_status(db))
    services.extend(_integration_status(db))
    from app.services import syslog

    sc = syslog.get_config(db)
    if sc["enabled"]:
        f = syslog.forwarder
        services.append({"name": "Syslog forwarding", "category": "Logs", "state": "degraded" if f.last_error else "ok",
                         "latency_ms": None, "detail": f.last_error or f"{sc['protocol'].upper()} {sc['host']}:{sc['port']} · {f.sent} sent, {f.dropped} dropped"})
    return {"services": services}


def _llm_status(db: Session) -> list[dict]:
    """One line per AI provider. The check lists models, so it costs no tokens."""
    import time

    from sqlalchemy import select

    from app.models import LlmProvider
    from app.services import llm

    providers = db.scalars(select(LlmProvider).order_by(LlmProvider.name)).all()
    if not providers:
        return [{"name": "AI provider", "category": "AI", "state": "down", "latency_ms": None,
                 "detail": "none configured: the chat cannot answer"}]
    out = []
    for p in providers:
        t0 = time.perf_counter()
        ok, detail = llm.ping(llm.provider_config(p))
        out.append({"name": f"LLM: {p.name}" + (" (default)" if p.is_default else ""), "category": "AI",
                    "state": "ok" if ok else "down", "latency_ms": round((time.perf_counter() - t0) * 1000), "detail": detail})
    return out


def _integration_status(db: Session, limit: int = 25) -> list[dict]:
    """One line per active integration of an enabled plugin: its Test with a short timeout, all in
    parallel, so a few unreachable systems do not hold the page for minutes."""
    import time
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy import select

    from app.models import Integration, Tenant
    from app.services import integrations

    on = integrations.enabled_plugins(db)
    rows = db.execute(select(Integration, Tenant).join(Tenant, Tenant.id == Integration.tenant_id)
                      .where(Integration.enabled.is_(True), Tenant.status != "disabled")
                      .order_by(Tenant.name, Integration.name)).all()
    items = []
    for inst, tenant in rows:
        c = integrations.usable_connector(db, inst.plugin) if inst.plugin in on else None
        if c is not None:
            items.append((inst, c, f"{c.manifest.label}: {tenant.name} · {inst.name}"))
    if not items:
        return []

    def check(item):
        inst, c, _ = item
        t0 = time.perf_counter()
        ok, detail = integrations.test(db, inst, c, timeout=5)  # no query: the row is already loaded
        return ok, detail, round((time.perf_counter() - t0) * 1000)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, items[:limit]))
    out = [{"name": name, "category": "Integrations", "state": "ok" if ok else "down", "latency_ms": ms, "detail": detail}
           for (_, _, name), (ok, detail, ms) in zip(items[:limit], results, strict=True)]
    if len(items) > limit:
        out.append({"name": "More integrations", "category": "Integrations", "state": "ok", "latency_ms": None,
                    "detail": f"only the first {limit} are checked here"})
    return out


# --- Embedding and Qdrant ------------------------------------------------------

@router.get("/embedding")
def get_embedding(db: Session = Depends(get_db), _: User = Depends(super_admin)) -> dict:
    from app.models import PlatformSetting
    from app.services import embeddings, vector_index
    from app.worker.tasks import REINDEX_STATE

    out = embeddings.public_config(embeddings.get_config(db))
    row = db.get(PlatformSetting, REINDEX_STATE)
    out["reindex"] = row.value if row else None
    try:
        out["index"] = vector_index.stats()
    except Exception:  # noqa: BLE001 - shown as unavailable
        out["index"] = None
    return out


@router.put("/embedding")
def put_embedding(body: EmbeddingIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> dict:
    from app.services import embeddings

    if body.url is not None and not body.url.startswith(("http://", "https://")):
        raise HTTPException(422, "The URL must start with http:// or https://.")
    cfg = embeddings.save_config(db, body.url, body.model, body.api_key)
    log_event(db, "platform.embedding_updated", actor=admin, ip=client_ip(request),
              detail={"url": cfg["url"], "model": cfg["model"], "api_key_changed": body.api_key is not None})
    return embeddings.public_config(cfg)


@router.post("/embedding/test")
def test_embedding(db: Session = Depends(get_db), _: User = Depends(super_admin)) -> dict:
    from app.services import embeddings

    cfg = embeddings.get_config(db)
    try:
        vec = embeddings.embed(cfg, ["Mentis embedding test"])[0]
    except embeddings.EmbeddingError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "dimensions": len(vec), "model": cfg["model"]}


@router.post("/embedding/reindex", status_code=202)
def reindex(request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> dict:
    from app.models import PlatformSetting
    from app.services import jobs
    from app.worker.tasks import REINDEX_STATE

    row = db.get(PlatformSetting, REINDEX_STATE)
    if row and row.value.get("status") in ("queued", "running"):
        raise HTTPException(409, "A reindex is already running.")
    if row is None:
        db.add(PlatformSetting(key=REINDEX_STATE, value={"status": "queued"}))
    else:
        row.value = {"status": "queued"}
    db.commit()
    try:
        jobs.enqueue_reindex()
    except Exception:  # noqa: BLE001 - Redis down: do not leave the state "queued" forever (it blocks every later reindex)
        row = db.get(PlatformSetting, REINDEX_STATE)
        row.value = {"status": "failed", "error": "The job queue (Redis) is not reachable. Try again later."}
        db.commit()
        raise HTTPException(503, "The job queue (Redis) is not reachable. Try again later.") from None
    log_event(db, "index.reindex_requested", actor=admin, ip=client_ip(request))
    return {"status": "queued"}
