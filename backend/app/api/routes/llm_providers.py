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
    role: str = Field(default=llm_config.ANSWERS, pattern="^(answers|checker)$")  # writes answers, or checks them


class ProviderOut(BaseModel):
    id: uuid.UUID
    name: str
    kind: str | None = None        # the fields below are for super-admins only
    base_url: str | None = None
    model: str
    api_key_set: bool | None = None
    options: dict | None = None
    is_default: bool
    role: str = llm_config.ANSWERS


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
    checker_id: uuid.UUID | None = None   # None = platform default checker (or the customer's own LLM)
    answer_check: str | None = Field(default=None, pattern="^(warn|hide|off)$")  # None = unchanged
    # Token limit of each level-2 check call; null = default. Changed only when sent.
    check_max_tokens: int | None = Field(default=None, ge=500, le=16000)


def _out(p: LlmProvider) -> ProviderOut:
    return ProviderOut(id=p.id, name=p.name, kind=p.kind, base_url=p.base_url, model=p.model,
                       api_key_set=bool(p.api_key_enc), options=p.options or {}, is_default=p.is_default, role=p.role)


def _validate(body: ProviderIn) -> None:
    problem = llm_config.provider_problem(body.kind, body.base_url, body.options)
    if problem:
        raise HTTPException(422, problem)


def _set_default(db: Session, p: LlmProvider) -> None:
    """One default per role: the default answering model, and the default checker."""
    db.execute(update(LlmProvider).where(LlmProvider.id != p.id, LlmProvider.role == p.role).values(is_default=False))
    p.is_default = True


def _in_use(db: Session, p: LlmProvider) -> list[str]:
    keys = ("llm_provider_id", "llm_fallback_id", "checker_provider_id")
    return [t.name for t in db.scalars(select(Tenant)) if str(p.id) in [(t.settings or {}).get(k) for k in keys]]


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
        if p is not None and p.api_key_enc:
            # The stored key goes only to the address it was saved for, never to one typed in the form.
            if not llm_config.same_origin(p.base_url, body.base_url):
                raise HTTPException(422, "Enter the API key to list the models at this address.")
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
    return [ProviderOut(id=p.id, name=p.name, model=p.model, is_default=p.is_default, role=p.role) for p in rows]


@router.post("/llm/providers", response_model=ProviderOut, status_code=201)
def create_provider(body: ProviderIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> ProviderOut:
    _validate(body)
    p = LlmProvider(name=body.name.strip(), kind=body.kind, base_url=body.base_url.rstrip("/"), model=body.model.strip(),
                    api_key_enc=crypto.encrypt(body.api_key) if body.api_key else None, options=body.options, role=body.role)
    db.add(p)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "A provider with this name already exists.") from None
    # The first model of a role becomes its default; adding another never changes the default by itself.
    first = db.scalar(select(LlmProvider.id).where(LlmProvider.id != p.id, LlmProvider.role == p.role)) is None
    if body.is_default or first:
        _set_default(db, p)
    db.commit()
    log_event(db, "llm.provider_created", actor=admin, target=p.name, ip=client_ip(request), detail={"kind": p.kind, "model": p.model, "role": p.role})
    return _out(p)


@router.put("/llm/providers/{provider_id}", response_model=ProviderOut)
def update_provider(provider_id: uuid.UUID, body: ProviderIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> ProviderOut:
    _validate(body)
    p = db.get(LlmProvider, provider_id)
    if p is None:
        raise HTTPException(404, "Provider not found.")
    if body.api_key is None and p.api_key_enc and not llm_config.same_origin(p.base_url, body.base_url):
        # Otherwise the stored key would be sent to the new address without the admin ever typing it.
        raise HTTPException(422, "Enter the API key again when you change the provider's address.")
    if body.role != p.role:
        if _in_use(db, p):
            raise HTTPException(409, f"In use by: {', '.join(_in_use(db, p))}. Change their LLM first.")
        if p.is_default:
            raise HTTPException(409, "Make another model the default first.")
        p.role = body.role
        if db.scalar(select(LlmProvider.id).where(LlmProvider.id != p.id, LlmProvider.role == p.role)) is None:
            body.is_default = True
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
    users = _in_use(db, p)
    if users:
        raise HTTPException(409, f"In use by: {', '.join(users)}. Change their LLM first.")
    was_default, name, role = p.is_default, p.name, p.role
    db.delete(p)
    db.flush()
    if was_default:
        nxt = db.scalar(select(LlmProvider).where(LlmProvider.role == role).order_by(LlmProvider.created_at))
        if nxt:
            nxt.is_default = True
    db.commit()
    log_event(db, "llm.provider_deleted", level="warning", actor=admin, target=name, ip=client_ip(request))


@router.post("/llm/providers/{provider_id}/default", response_model=ProviderOut)
def make_default(provider_id: uuid.UUID, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> ProviderOut:
    """Set as default of its role (answers, or answer check)."""
    p = db.get(LlmProvider, provider_id)
    if p is None:
        raise HTTPException(404, "Provider not found.")
    _set_default(db, p)
    db.commit()
    log_event(db, "llm.provider_default", actor=admin, target=p.name, ip=client_ip(request), detail={"role": p.role})
    return _out(p)


@router.post("/llm/providers/{provider_id}/test")
def test_provider(provider_id: uuid.UUID, db: Session = Depends(get_db), _: User = Depends(super_admin)) -> dict:
    p = db.get(LlmProvider, provider_id)
    if p is None:
        raise HTTPException(404, "Provider not found.")
    if p.role == llm_config.CHECKER:
        return _test_checker(p)
    try:
        reply = llm.call_provider(llm.provider_config(p), "Reply with the single word: ready", [llm.Turn("user", "Are you ready?")], timeout=60)
    except llm.LLMError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "reply": reply.text[:200]}


SAMPLE_PASSAGE = ("Brute force attacks on VPN accounts: call the SOC on-call contact Mario Rossi, phone +39 085 111 2233. "
                  "Critical incidents must be escalated within 30 minutes.")
SAMPLE_ANSWER = "Call **Mario Rossi**, +39 085 111 2233 [1]. Critical incidents must be escalated within **2 hours** [1]."


def _test_checker(p: LlmProvider) -> dict:
    """The checker gets a sample answer with a planted error (2 hours instead of 30 minutes)."""
    from app.services import answer_check

    try:
        issues, verdict = answer_check.level2(llm.provider_config(p), SAMPLE_ANSWER, {1: SAMPLE_PASSAGE})
    except llm.LLMError as e:
        return {"ok": False, "error": str(e)}
    caught = any("2 hours" in i["text"] for i in issues)
    wrong = [i for i in issues if "2 hours" not in i["text"]]
    if caught and not wrong:
        return {"ok": True, "reply": f"caught the planted error ({verdict.latency_ms / 1000:.1f} s)"}
    if not caught:
        return {"ok": False, "error": "the checker did not catch the planted error (2 hours instead of 30 minutes)"}
    return {"ok": False, "error": "the checker also rejected a correct statement"}


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
    from app.services import answer_check
    from app.services.answer_check import judge

    return {"provider_id": s.get("llm_provider_id"), "fallback_id": s.get("llm_fallback_id"), "editable": _editable(user, t),
            "admin_can_set_llm": bool(s.get("admin_can_set_llm", True)),
            "checker_id": s.get("checker_provider_id"), "answer_check": answer_check.mode_of(s),
            "check_max_tokens": s.get("check_max_tokens"), "check_max_tokens_default": judge.DEFAULT_MAX_TOKENS}


@router.put("/tenants/{tenant_id}/llm")
def put_tenant_llm(tenant_id: uuid.UUID, body: TenantLlmIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)) -> dict:
    t = _tenant_for(db, user, tenant_id)
    s = t.settings or {}
    same_models = (str(body.provider_id) if body.provider_id else None, str(body.fallback_id) if body.fallback_id else None,
                   str(body.checker_id) if body.checker_id else None) == (s.get("llm_provider_id"), s.get("llm_fallback_id"), s.get("checker_provider_id"))
    # When the super-admin chooses the models, the tenant admin can still set what the answer check does.
    if not _editable(user, t) and not same_models:
        raise HTTPException(403, "The super-admin chooses the LLM of this customer.")
    for pid, role in ((body.provider_id, llm_config.ANSWERS), (body.fallback_id, llm_config.ANSWERS), (body.checker_id, llm_config.CHECKER)):
        if pid is None:
            continue
        p = db.get(LlmProvider, pid)
        if p is None:
            raise HTTPException(422, "Unknown provider.")
        if p.role != role:
            raise HTTPException(422, f"{p.name} is not a model for {'answers' if role == llm_config.ANSWERS else 'the answer check'}.")
    t.settings = {**(t.settings or {}), "llm_provider_id": str(body.provider_id) if body.provider_id else None,
                  "llm_fallback_id": str(body.fallback_id) if body.fallback_id else None,
                  "checker_provider_id": str(body.checker_id) if body.checker_id else None}
    if body.answer_check is not None:
        t.settings = {**t.settings, "answer_check": body.answer_check}
    if "check_max_tokens" in body.model_fields_set:  # like the mode: the tenant admin may always set it
        t.settings = {**t.settings, "check_max_tokens": body.check_max_tokens}
    db.commit()
    log_event(db, "tenant.llm_updated", actor=user, tenant_id=t.id, target=t.name, ip=client_ip(request),
              detail={"provider_id": t.settings["llm_provider_id"], "fallback_id": t.settings["llm_fallback_id"],
                      "checker_id": t.settings["checker_provider_id"], "answer_check": t.settings.get("answer_check", "warn"),
                      "check_max_tokens": t.settings.get("check_max_tokens")})
    return get_tenant_llm(tenant_id, db, user)
