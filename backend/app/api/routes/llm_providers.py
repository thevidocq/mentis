"""AI providers (super-admin) and a tenant's LLM choice (super-admin or that tenant's admin)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip, current_user, require_roles
from app.core import crypto
from app.core.db import get_db
from app.models import LlmProvider, Role, Tenant, User
from app.services import access, llm, llm_config
from app.services.logs import log_event

router = APIRouter(tags=["llm"])
super_admin = require_roles(Role.SUPER_ADMIN)


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str
    base_url: str = Field(min_length=8, max_length=500)
    model: str = Field(min_length=1, max_length=200)
    api_key: str | None = None  # write-only; omit to keep, "" to clear
    options: dict = Field(default_factory=dict)
    is_default: bool = False


class ProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str | None = None        # the fields below are for super-admins only
    base_url: str | None = None
    model: str
    api_key_set: bool | None = None
    options: dict | None = None
    is_default: bool


class ModelsIn(BaseModel):
    kind: str
    base_url: str = Field(min_length=8, max_length=500)
    api_key: str | None = None        # as typed in the form; omitted = use the stored key of provider_id
    provider_id: uuid.UUID | None = None


class ModelOption(BaseModel):
    id: str
    label: str


class TenantLlmIn(BaseModel):
    provider_id: uuid.UUID | None = None  # None = platform default
    fallback_id: uuid.UUID | None = None


def _out(p: LlmProvider) -> ProviderOut:
    return ProviderOut(id=p.id, name=p.name, kind=p.kind, base_url=p.base_url, model=p.model,
                       api_key_set=bool(p.api_key_enc), options=p.options or {}, is_default=p.is_default)


def _validate(body: ProviderIn) -> None:
    problem = llm_config.provider_problem(body.kind, body.base_url, body.options)
    if problem:
        raise HTTPException(422, problem)


def _set_default(db: Session, p: LlmProvider) -> None:
    db.execute(update(LlmProvider).where(LlmProvider.id != p.id).values(is_default=False))
    p.is_default = True


@router.get("/llm/kinds")
def kinds(_: User = Depends(super_admin)) -> dict:
    return {"kinds": llm.KINDS, "presets": llm.PRESETS}


@router.post("/llm/models", response_model=list[ModelOption])
def provider_models(body: ModelsIn, db: Session = Depends(get_db), _: User = Depends(super_admin)) -> list[ModelOption]:
    """The models a provider offers, to pick from in the form instead of typing a name."""
    if body.kind not in llm.KINDS:
        raise HTTPException(422, "Unknown provider type.")
    if not body.base_url.startswith(("http://", "https://")):
        raise HTTPException(422, "The URL must start with http:// or https://.")
    api_key = body.api_key or None
    if api_key is None and body.provider_id is not None:
        p = db.get(LlmProvider, body.provider_id)
        # The stored key goes only to the address it was saved for.
        if p is not None and p.api_key_enc and p.base_url == body.base_url.rstrip("/"):
            api_key = crypto.decrypt(p.api_key_enc)
    try:
        models = llm.list_models({"name": "The provider", "kind": body.kind, "base_url": body.base_url.rstrip("/"), "api_key": api_key})
    except llm.LLMError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Could not list the models: {e}") from None
    return [ModelOption(**m) for m in models]


@router.get("/llm/providers", response_model=list[ProviderOut])
def list_providers(db: Session = Depends(get_db), user: User = Depends(current_user)) -> list[ProviderOut]:
    # Tenant admins see the list to choose from; only super-admins manage it.
    if user.role == Role.ANALYST.value:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role.")
    rows = db.scalars(select(LlmProvider).order_by(LlmProvider.name))
    if user.role == Role.SUPER_ADMIN.value:
        return [_out(p) for p in rows]
    # Tenant admins only need to recognise a model: no addresses, keys or prices.
    return [ProviderOut(id=p.id, name=p.name, model=p.model, is_default=p.is_default) for p in rows]


@router.post("/llm/providers", response_model=ProviderOut, status_code=201)
def create_provider(body: ProviderIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> ProviderOut:
    _validate(body)
    p = LlmProvider(name=body.name.strip(), kind=body.kind, base_url=body.base_url.rstrip("/"), model=body.model.strip(),
                    api_key_enc=crypto.encrypt(body.api_key) if body.api_key else None, options=body.options)
    db.add(p)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A provider with this name already exists.") from None
    first = db.scalar(select(LlmProvider.id).where(LlmProvider.id != p.id)) is None
    if body.is_default or first:
        _set_default(db, p)
    db.commit()
    log_event(db, "llm.provider_created", actor=admin, target=p.name, ip=client_ip(request), detail={"kind": p.kind, "model": p.model})
    return _out(p)


@router.put("/llm/providers/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: uuid.UUID, body: ProviderIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> ProviderOut:
    _validate(body)
    p = db.get(LlmProvider, provider_id)
    if p is None:
        raise HTTPException(404, "Provider not found.")
    # A stored key is never sent to a new address: it could be pointed at a server that records it.
    if p.api_key_enc and body.base_url.rstrip("/") != p.base_url and not body.api_key:
        raise HTTPException(422, "Enter the API key again when you change the URL.")
    p.name, p.kind, p.base_url, p.model, p.options = body.name.strip(), body.kind, body.base_url.rstrip("/"), body.model.strip(), body.options
    if body.api_key is not None:
        p.api_key_enc = crypto.encrypt(body.api_key) if body.api_key else None
    if body.is_default:
        _set_default(db, p)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A provider with this name already exists.") from None
    log_event(db, "llm.provider_updated", actor=admin, target=p.name, ip=client_ip(request), detail={"kind": p.kind, "model": p.model})
    return _out(p)


@router.delete("/llm/providers/{provider_id}", status_code=204)
def delete_provider(provider_id: uuid.UUID, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> None:
    p = db.get(LlmProvider, provider_id)
    if p is None:
        raise HTTPException(404, "Provider not found.")
    users = [t.name for t in db.scalars(select(Tenant)) if str(p.id) in ((t.settings or {}).get("llm_provider_id"), (t.settings or {}).get("llm_fallback_id"))]
    if users:
        raise HTTPException(409, f"In use by: {', '.join(users)}. Change their LLM first.")
    was_default, name = p.is_default, p.name
    db.delete(p)
    db.flush()
    if was_default:
        nxt = db.scalar(select(LlmProvider).order_by(LlmProvider.created_at))
        if nxt:
            nxt.is_default = True
    db.commit()
    log_event(db, "llm.provider_deleted", level="warning", actor=admin, target=name, ip=client_ip(request))


@router.post("/llm/providers/{provider_id}/test")
def test_provider(provider_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(super_admin)) -> dict:
    p = db.get(LlmProvider, provider_id)
    if p is None:
        raise HTTPException(404, "Provider not found.")
    try:
        reply = llm.call_provider(llm.provider_config(p), "Reply with the single word: ready", [llm.Turn("user", "Are you ready?")], timeout=60)
    except llm.LLMError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "reply": reply.text[:200]}


# --- Tenant choice ---------------------------------------------------------------

def _tenant_for(db: Session, user: User, tenant_id: uuid.UUID) -> Tenant:
    t = db.get(Tenant, tenant_id)
    ok = t is not None and (user.role == Role.SUPER_ADMIN.value or access.administers(db, user, tenant_id))
    if not ok:
        raise HTTPException(404, "Tenant not found.")
    return t


def _editable(user: User, t: Tenant) -> bool:
    """Super-admins always; tenant admins when the super-admin allows it for this tenant."""
    return user.role == Role.SUPER_ADMIN.value or bool((t.settings or {}).get("admin_can_set_llm", True))


@router.get("/tenants/{tenant_id}/llm")
def get_tenant_llm(tenant_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    t = _tenant_for(db, user, tenant_id)
    s = t.settings or {}
    return {"provider_id": s.get("llm_provider_id"), "fallback_id": s.get("llm_fallback_id"), "editable": _editable(user, t),
            "admin_can_set_llm": bool(s.get("admin_can_set_llm", True))}


@router.put("/tenants/{tenant_id}/llm")
def put_tenant_llm(tenant_id: uuid.UUID, body: TenantLlmIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    t = _tenant_for(db, user, tenant_id)
    if not _editable(user, t):
        raise HTTPException(403, "The super-admin chooses the LLM of this customer.")
    for pid in (body.provider_id, body.fallback_id):
        if pid is not None and db.get(LlmProvider, pid) is None:
            raise HTTPException(422, "Unknown provider.")
    t.settings = {**(t.settings or {}), "llm_provider_id": str(body.provider_id) if body.provider_id else None,
                  "llm_fallback_id": str(body.fallback_id) if body.fallback_id else None}
    db.commit()
    log_event(db, "tenant.llm_updated", actor=user, tenant_id=t.id, target=t.name, ip=client_ip(request),
              detail={"provider_id": t.settings["llm_provider_id"], "fallback_id": t.settings["llm_fallback_id"]})
    return get_tenant_llm(tenant_id, db, user)
