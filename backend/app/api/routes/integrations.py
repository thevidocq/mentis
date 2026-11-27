"""Integrations: plugins enabled by the super-admin, instances configured by the customer's tenant admins.

- Super-admins: which installed plugins may be used (`/platform/integrations`). They see no
  instance configuration (customer systems), only counts and the Service status.
- Tenant admins of a customer: its instances (create, edit, test, try a lookup, delete). The
  General Knowledge Base has no integrations. Secrets are write-only.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.core.ratelimit import user_rate_limit
from app.connectors import registry, schema
from app.connectors.contract import Connector
from app.core.db import get_db
from app.models import Integration, Role, Tenant, User
from app.models.base import utcnow
from app.services import access, integrations
from app.services.integrations.instances import IntegrationFailed, secrets_of, store_secrets
from app.services.logs import log_event

router = APIRouter(tags=["integrations"])
super_admin = require_roles(Role.SUPER_ADMIN)
tenant_admin = require_roles(Role.TENANT_ADMIN)
admins = require_roles(Role.SUPER_ADMIN, Role.TENANT_ADMIN)


# --- Schemas -------------------------------------------------------------------

class OperationOut(BaseModel):
    name: str
    label: str
    description: str
    returns: str
    params: dict[str, str]  # name -> description


class PluginOut(BaseModel):
    name: str
    label: str
    type: str
    vendor: str
    version: str
    description: str
    operations: list[OperationOut]
    enabled: bool = True
    instances: int | None = None          # super-admins: how many customers use it
    config_schema: dict | None = None     # tenant admins: the form


class PluginsIn(BaseModel):
    enabled: list[str] = Field(max_length=100)


class IntegrationSettingsIn(BaseModel):
    allow_private: bool  # private network addresses and plain HTTP (on-premise systems)


class IntegrationIn(BaseModel):
    plugin: str | None = Field(default=None, max_length=64)  # required on create
    name: str | None = Field(default=None, min_length=1, max_length=80)
    config: dict | None = None   # values of the plugin's schema; secrets omitted = kept, "" = cleared
    enabled: bool | None = None


class IntegrationOut(BaseModel):
    id: uuid.UUID
    plugin: str
    product: str
    type: str | None
    name: str
    config: dict
    secrets_set: dict[str, bool]
    enabled: bool
    available: bool   # plugin installed and enabled by the super-admin
    updated_at: datetime


class ModeIn(BaseModel):
    mode: str = Field(pattern="^(standard|tools)$")


class RunIn(BaseModel):
    operation: str = Field(min_length=1, max_length=64)
    args: dict = Field(default_factory=dict)


# --- Helpers -------------------------------------------------------------------

def _plugin_out(c: Connector, **extra) -> PluginOut:
    m = c.manifest
    ops = [OperationOut(name=o.name, label=o.label, description=o.description, returns=o.returns,
                        params={k: p.description for k, p in o.params.items()}) for o in c.operations]
    return PluginOut(name=m.name, label=m.label, type=m.type, vendor=m.vendor, version=m.version,
                     description=m.description, operations=ops, **extra)


def _out(db: Session, inst: Integration) -> IntegrationOut:
    c = registry.get(inst.plugin)
    stored = secrets_of(inst)
    keys = schema.secret_keys(c) if c else set(stored)
    return IntegrationOut(id=inst.id, plugin=inst.plugin, product=c.manifest.label if c else inst.plugin,
                          type=c.manifest.type if c else None, name=inst.name, config=dict(inst.config or {}),
                          secrets_set={k: bool(stored.get(k)) for k in sorted(keys)}, enabled=inst.enabled,
                          available=integrations.usable_connector(db, inst.plugin) is not None, updated_at=inst.updated_at)


def _tenant(db: Session, user: User, tenant_id: uuid.UUID) -> Tenant:
    """A customer this tenant admin administers (404 otherwise, like documents)."""
    t = db.get(Tenant, tenant_id)
    if t is None or not access.administers(db, user, t.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found.")
    return t


def _instance(db: Session, user: User, tenant_id: uuid.UUID, integration_id: uuid.UUID) -> tuple[Tenant, Integration]:
    t = _tenant(db, user, tenant_id)
    inst = db.get(Integration, integration_id)
    if inst is None or inst.tenant_id != t.id:  # another customer's id under this one: not found
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integration not found.")
    return t, inst


def _active(t: Tenant) -> None:
    """No calls to a disabled customer's systems (its settings can still be edited or deleted)."""
    if t.status == "disabled":
        raise HTTPException(status.HTTP_409_CONFLICT, "This customer is disabled.")


def _connector(db: Session, plugin: str) -> Connector:
    c = integrations.usable_connector(db, plugin)
    if c is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "This integration type is not enabled. Ask a super-admin.")
    return c


def _origins(c: Connector, config: dict) -> set[str] | None:
    try:
        c.read_posts(config)  # validates the rest of the address (e.g. a tenant id in a token URL)
        return {o.lower() for o in c.origins(config)}
    except Exception:  # noqa: BLE001 - an address the plugin cannot read
        return None


# --- Super-admin: plugins ------------------------------------------------------

@router.get("/platform/integrations", response_model=list[PluginOut])
def list_plugins(db: Session = Depends(get_db), _: User = Depends(super_admin)) -> list[PluginOut]:
    on = integrations.enabled_plugins(db)
    counts = dict(db.execute(select(Integration.plugin, func.count()).group_by(Integration.plugin)).all())
    return [_plugin_out(c, enabled=name in on, instances=counts.get(name, 0)) for name, c in registry.connectors().items()]


@router.put("/platform/integrations", response_model=list[PluginOut])
def set_plugins(body: PluginsIn, request: Request, db: Session = Depends(get_db), admin: User = Depends(super_admin)) -> list[PluginOut]:
    installed = registry.connectors()
    unknown = [n for n in body.enabled if n not in installed]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Not installed: {', '.join(unknown)[:200]}")
    before = integrations.enabled_plugins(db)
    after = set(body.enabled)
    integrations.set_enabled_plugins(db, after)
    log_event(db, "platform.integrations", actor=admin, ip=client_ip(request),
              detail={"enabled": sorted(after - before), "disabled": sorted(before - after)}, commit=False)
    db.commit()
    return list_plugins(db, admin)


@router.get("/platform/integrations/settings")
def get_integration_settings(db: Session = Depends(get_db), _: User = Depends(super_admin)) -> dict:
    return {"allow_private": integrations.instances.allow_private(db)}


@router.put("/platform/integrations/settings")
def put_integration_settings(body: IntegrationSettingsIn, request: Request, db: Session = Depends(get_db),
                             admin: User = Depends(super_admin)) -> dict:
    """Private addresses (10/8, 172.16/12, 192.168/16...) and plain HTTP for on-premise systems.
    Mentis' own services, loopback and cloud metadata stay refused either way."""
    integrations.instances.set_allow_private(db, body.allow_private)
    log_event(db, "platform.integrations", level="warning" if body.allow_private else "info", actor=admin,
              ip=client_ip(request), detail={"allow_private": body.allow_private}, commit=False)
    db.commit()
    return {"allow_private": body.allow_private}


# --- Tenant admin: instances ---------------------------------------------------

@router.get("/tenants/{tenant_id}/integrations")
def list_integrations(tenant_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(tenant_admin)) -> dict:
    """The customer's integrations, and the types that can be added (enabled by the super-admin)."""
    t = _tenant(db, user, tenant_id)
    on = integrations.enabled_plugins(db)
    plugins = [] if t.is_global else [
        _plugin_out(c, config_schema=schema.public_schema(c)) for n, c in registry.connectors().items() if n in on]
    rows = db.scalars(select(Integration).where(Integration.tenant_id == t.id).order_by(Integration.name)).all()
    return {"plugins": [p.model_dump() for p in plugins], "integrations": [_out(db, i).model_dump(mode="json") for i in rows],
            "general": t.is_global}


@router.post("/tenants/{tenant_id}/integrations", response_model=IntegrationOut, status_code=status.HTTP_201_CREATED)
def create_integration(tenant_id: uuid.UUID, body: IntegrationIn, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(tenant_admin)) -> IntegrationOut:
    t = _tenant(db, user, tenant_id)
    if not body.plugin or not body.name or body.config is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Type, name and configuration are required.")
    c = _connector(db, body.plugin)
    if t.is_global:
        raise HTTPException(status.HTTP_409_CONFLICT, "The General Knowledge Base has no integrations: add them to a customer.")
    config, secrets, problem = schema.split(c, body.config)
    if problem:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
    if _origins(c, config) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Check the address (or the tenant / region fields).")
    inst = Integration(tenant_id=t.id, plugin=body.plugin, name=body.name.strip(), config=config,
                       enabled=True if body.enabled is None else body.enabled)
    store_secrets(inst, secrets)
    db.add(inst)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This customer already has an integration with this name.") from None
    log_event(db, "integration.created", actor=user, tenant_id=t.id, target=str(inst.id), ip=client_ip(request),
              detail={"plugin": inst.plugin, "name": inst.name}, commit=False)
    db.commit()
    return _out(db, inst)


@router.put("/tenants/{tenant_id}/integrations/{integration_id}", response_model=IntegrationOut)
def update_integration(tenant_id: uuid.UUID, integration_id: uuid.UUID, body: IntegrationIn, request: Request,
                       db: Session = Depends(get_db), user: User = Depends(tenant_admin)) -> IntegrationOut:
    t, inst = _instance(db, user, tenant_id, integration_id)
    if body.plugin and body.plugin != inst.plugin:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The type of an integration cannot change: add a new one.")
    changed = []
    if body.config is not None:
        c = _connector(db, inst.plugin)
        stored = secrets_of(inst)
        config, secrets, problem = schema.split(c, body.config, stored)
        if problem:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, problem)
        if _origins(c, config) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Check the address.")
        # Stored secrets are bound to the address and to the fields that decide whose data they open
        # (tenant id, child CID, account, projects): changing either needs them again.
        resent = {k for k, v in body.config.items() if k in schema.secret_keys(c) and v}
        if schema.rebinds(c, inst.config or {}, config) and any(k not in resent for k in stored):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "The address or the account fields changed: enter the credentials again.")
        inst.config = config
        store_secrets(inst, secrets)
        changed.append("config")
    if body.name is not None and body.name.strip() != inst.name:
        inst.name = body.name.strip()
        changed.append("name")
    if body.enabled is not None and body.enabled != inst.enabled:
        inst.enabled = body.enabled
        changed.append("enabled" if body.enabled else "disabled")
    inst.updated_at = utcnow()
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "This customer already has an integration with this name.") from None
    log_event(db, "integration.updated", actor=user, tenant_id=t.id, target=str(inst.id), ip=client_ip(request),
              detail={"plugin": inst.plugin, "name": inst.name, "changed": changed}, commit=False)
    db.commit()
    return _out(db, inst)


@router.delete("/tenants/{tenant_id}/integrations/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_integration(tenant_id: uuid.UUID, integration_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                       user: User = Depends(tenant_admin)) -> None:
    t, inst = _instance(db, user, tenant_id, integration_id)
    log_event(db, "integration.deleted", actor=user, tenant_id=t.id, target=str(inst.id), ip=client_ip(request),
              detail={"plugin": inst.plugin, "name": inst.name}, commit=False)
    db.delete(inst)
    db.commit()  # chats keep the id; it is ignored from now on (see integrations.for_chat)


@router.post("/tenants/{tenant_id}/integrations/{integration_id}/test")
def test_integration(tenant_id: uuid.UUID, integration_id: uuid.UUID, request: Request, db: Session = Depends(get_db),
                     user: User = Depends(tenant_admin)) -> dict:
    t, inst = _instance(db, user, tenant_id, integration_id)
    _active(t)
    user_rate_limit(request, user.id, "lookup")
    c = _connector(db, inst.plugin)
    ok, detail = integrations.test(db, inst, c)
    log_event(db, "integration.tested", kind="audit", level="info" if ok else "warning", actor=user, tenant_id=t.id,
              target=str(inst.id), ip=client_ip(request), detail={"plugin": inst.plugin, "ok": ok, "detail": detail})
    return {"ok": ok, "detail": detail}


@router.post("/tenants/{tenant_id}/integrations/{integration_id}/run")
def try_lookup(tenant_id: uuid.UUID, integration_id: uuid.UUID, body: RunIn, request: Request, db: Session = Depends(get_db),
               user: User = Depends(tenant_admin)) -> dict:
    """"Try a lookup": runs one read operation, to check the configuration and the field mapping."""
    t, inst = _instance(db, user, tenant_id, integration_id)
    _active(t)
    user_rate_limit(request, user.id, "lookup")
    c = _connector(db, inst.plugin)
    if c.operation(body.operation) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown operation.")
    try:
        records = integrations.run(db, inst, c, body.operation, body.args, actor=user, purpose="try")
    except IntegrationFailed as e:
        db.commit()  # keep the audit entry
        return {"ok": False, "detail": e.public, "records": []}
    db.commit()
    return {"ok": True, "detail": f"{len(records)} found",
            "records": [{"kind": r.kind, "id": r.id, "title": r.title, "url": r.url, "fields": r.fields, "text": r.text,
                         "updated": r.updated, "links": r.links} for r in records]}


# --- Lookup mode (standard or function calling), per customer ----------------------------

def _mode_tenant(db: Session, user: User, tenant_id: uuid.UUID) -> Tenant:
    """Super-admins: any tenant; tenant admins: the customers they administer (404 otherwise)."""
    if user.role == Role.SUPER_ADMIN.value:
        t = db.get(Tenant, tenant_id)
        if t is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found.")
        return t
    return _tenant(db, user, tenant_id)


def _mode_out(t: Tenant, user: User) -> dict:
    """The mode, and whether this user may change it: super-admins always; tenant admins only when
    the customer uses its own LLM chosen by them (function calling depends on the model)."""
    s = t.settings or {}
    own_llm = bool(s.get("llm_provider_id"))
    admin_llm = s.get("admin_can_set_llm", True)
    editable = not t.is_global and (user.role == Role.SUPER_ADMIN.value or (own_llm and admin_llm))
    reason = None
    if t.is_global:
        reason = "The General Knowledge Base has no integrations."
    elif not editable:
        reason = ("This customer uses the platform's LLM: a super-admin chooses the mode." if not own_llm
                  else "The LLM of this customer is chosen by a super-admin, who also chooses the mode.")
    from app.services.integrations.live import mode_of

    return {"mode": mode_of(s), "editable": editable, "reason": reason, "own_llm": own_llm}


@router.get("/tenants/{tenant_id}/integration-mode")
def get_mode(tenant_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(admins)) -> dict:
    return _mode_out(_mode_tenant(db, user, tenant_id), user)


@router.put("/tenants/{tenant_id}/integration-mode")
def set_mode(tenant_id: uuid.UUID, body: ModeIn, request: Request, db: Session = Depends(get_db),
             user: User = Depends(admins)) -> dict:
    t = _mode_tenant(db, user, tenant_id)
    current = _mode_out(t, user)
    if t.is_global:
        raise HTTPException(status.HTTP_409_CONFLICT, current["reason"])
    if not current["editable"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, current["reason"])
    if body.mode != current["mode"]:
        by = "super_admin" if user.role == Role.SUPER_ADMIN.value else "tenant_admin"
        t.settings = {**(t.settings or {}), "integration_mode": body.mode, "integration_mode_by": by}
        log_event(db, "tenant.integration_mode", actor=user, tenant_id=t.id, target=t.name, ip=client_ip(request),
                  detail={"from": current["mode"], "to": body.mode}, commit=False)
        db.commit()
    return _mode_out(t, user)
