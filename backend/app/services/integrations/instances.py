"""Integration instances: secrets, plugin availability, and running operations with the core's guards.

Guards on every call: the instance belongs to the tenant the caller asked for (checked by the
callers against the chat or the route), the plugin is installed and enabled by the super-admin,
arguments match the operation's declared parameters, the HTTP client only reads from the
instance's origins, results are capped, and an `integration.called` entry goes to the Logs
(which integration, which operation, which object; never search words or results).
"""

import hashlib
import json
import logging
import re
import time
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors import registry
from app.connectors.contract import Connector, ConnectorError, Context, Operation, Record
from app.connectors.http import SafeHttp
from app.core import crypto
from app.models import Chat, Integration, PlatformSetting, Tenant, User
from app.services.logs import log_event

_log = logging.getLogger("mentis.integrations")

KEY = "integrations"          # platform setting: {"enabled": ["servicenow", ...]}
MAX_RECORDS = 10              # per operation
MAX_TEXT = 3000               # characters of long text per record
MAX_FIELDS = 30

# OAuth tokens and similar per instance, dropped when the configuration changes.
_state: dict[uuid.UUID, tuple[str, dict]] = {}


class IntegrationFailed(Exception):
    """An operation failed. `public` is a plain message for analysts; `detail` goes to the logs."""

    def __init__(self, public: str, detail: str):
        super().__init__(detail)
        self.public = public
        self.detail = detail


# --- Plugins enabled by the super-admin -----------------------------------------------------

def enabled_plugins(db: Session) -> set[str]:
    row = db.get(PlatformSetting, KEY)
    names = (row.value or {}).get("enabled", []) if row else []
    return {n for n in names if isinstance(n, str)}


def set_enabled_plugins(db: Session, names: set[str]) -> None:
    row = db.get(PlatformSetting, KEY)
    value = {"enabled": sorted(names)}
    if row is None:
        db.add(PlatformSetting(key=KEY, value=value))
    else:
        row.value = value


def usable_connector(db: Session, plugin: str) -> Connector | None:
    """The plugin, if it is installed and enabled."""
    c = registry.get(plugin)
    return c if c is not None and plugin in enabled_plugins(db) else None


# --- Secrets --------------------------------------------------------------------------------

def secrets_of(inst: Integration) -> dict:
    if not inst.secrets_enc:
        return {}
    raw = crypto.decrypt(inst.secrets_enc)
    try:
        data = json.loads(raw) if raw else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def store_secrets(inst: Integration, secrets: dict) -> None:
    inst.secrets_enc = crypto.encrypt(json.dumps(secrets)) if secrets else None
    _state.pop(inst.id, None)


def _redact(text: str, secrets: dict) -> str:
    for v in secrets.values():
        if isinstance(v, str) and len(v) >= 4:
            text = text.replace(v, "[redacted]")
    return text


# --- Which instances a chat may use ---------------------------------------------------------

def selectable(db: Session, tenant: Tenant) -> list[tuple[Integration, Connector]]:
    """Instances of a customer that can be used now (enabled, plugin installed and enabled).
    The General Knowledge Base has no integrations (no customer context)."""
    if tenant.is_global or tenant.status == "disabled":
        return []
    on = enabled_plugins(db)
    out = []
    for inst in db.scalars(select(Integration).where(Integration.tenant_id == tenant.id, Integration.enabled.is_(True))
                           .order_by(Integration.name)):
        c = registry.get(inst.plugin)
        if c is not None and inst.plugin in on:
            out.append((inst, c))
    return out


def for_chat(db: Session, chat: Chat) -> list[tuple[Integration, Connector]]:
    """The chat's # integrations that are still usable. The tenant comes from the chat, never
    from the request: an id of another customer's instance is simply ignored."""
    if chat.scope_tenant_id is None or not chat.integration_ids:
        return []
    tenant = db.get(Tenant, chat.scope_tenant_id)
    if tenant is None:
        return []
    wanted = {str(i) for i in chat.integration_ids}
    return [(i, c) for i, c in selectable(db, tenant) if str(i.id) in wanted]


# --- Running operations ---------------------------------------------------------------------

def check_args(op: Operation, args: dict) -> dict:
    """Only declared parameters, as text, matching their pattern. Raises ValueError."""
    if not isinstance(args, dict):
        raise ValueError("arguments must be an object")
    clean = {}
    for name, spec in op.params.items():
        value = args.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            if spec.required:
                raise ValueError(f"missing {name}")
            continue
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError(f"{name} must be text")
        value = " ".join(str(value).replace("\x00", "").split())
        if len(value) > spec.max_length:
            raise ValueError(f"{name} too long")
        if spec.pattern and not re.fullmatch(spec.pattern, value):
            raise ValueError(f"{name} has an invalid format")
        clean[name] = value
    return clean


def _fingerprint(inst: Integration) -> str:
    return hashlib.sha256(json.dumps([inst.plugin, inst.config, inst.secrets_enc], sort_keys=True, default=str).encode()).hexdigest()


def _context(inst: Integration, c: Connector, secrets: dict, timeout: float) -> tuple[Context, SafeHttp]:
    fp = _fingerprint(inst)
    saved = _state.get(inst.id)
    state = saved[1] if saved and saved[0] == fp else {}
    _state[inst.id] = (fp, state)
    http = SafeHttp(c.manifest.label, c.origins(inst.config or {}), c.read_posts(inst.config or {}), timeout=timeout)
    return Context(config=dict(inst.config or {}), secrets=secrets, http=http, state=state), http


def _clean(records: list[Record]) -> list[Record]:
    out = []
    for r in list(records or [])[:MAX_RECORDS]:
        if not isinstance(r, Record):
            continue
        fields = {str(k)[:60]: str(v)[:500] for k, v in list((r.fields or {}).items())[:MAX_FIELDS] if v not in (None, "")}
        text = (r.text or "").replace("\x00", "")
        links = {str(k)[:80]: v for k, v in list((r.links or {}).items())[:5] if _web(v)}
        out.append(Record(kind=r.kind, id=str(r.id)[:200], title=str(r.title or "")[:300], fields=fields,
                          text=text[:MAX_TEXT] + ("…" if len(text) > MAX_TEXT else "") if text else None,
                          url=r.url if _web(r.url) else None, links=links,
                          updated=str(r.updated)[:40] if r.updated else None))
    return out


def _web(url) -> bool:
    """A link the analyst may open: http(s), no spaces or brackets that would break Markdown."""
    return (isinstance(url, str) and len(url) <= 1000 and url.lower().startswith(("https://", "http://"))
            and not any(ch in url for ch in " \t\r\n<>()[]\"'`"))


def _public(e: Exception, label: str) -> str:
    if isinstance(e, ConnectorError) and e.public:
        return str(e)
    return f"{label} could not be read right now"


def run(db: Session, inst: Integration, c: Connector, operation: str, args: dict, *, actor: User | None,
        chat_id: uuid.UUID | None = None, purpose: str = "chat", timeout: float = 15) -> list[Record]:
    """Runs one read operation. Raises IntegrationFailed (with a public message)."""
    op = c.operation(operation)
    label = f"{c.manifest.label} ({inst.name})"
    if op is None:
        raise IntegrationFailed(f"{label}: unknown operation", f"unknown operation {operation}")
    try:
        clean = check_args(op, args)
    except ValueError as e:
        raise IntegrationFailed(f"{label}: {e}", f"invalid arguments: {e}") from None
    secrets = secrets_of(inst)
    ctx, http = _context(inst, c, secrets, timeout)
    t0 = time.perf_counter()
    detail = {"integration": str(inst.id), "name": inst.name, "plugin": inst.plugin, "operation": operation, "purpose": purpose,
              "object": {k: v for k, v in clean.items() if op.params[k].identifier},
              "chat": str(chat_id) if chat_id else None}
    try:
        records = _clean(c.run(ctx, operation, clean))
    except Exception as e:  # noqa: BLE001 - a plugin error must never break the chat
        if not isinstance(e, ConnectorError):
            _log.exception("integration %s (%s) failed", inst.id, inst.plugin)
        cause = _redact(str(e), secrets)[:300]
        log_event(db, "integration.called", kind="audit", level="error", actor=actor, tenant_id=inst.tenant_id,
                  target=str(inst.id), detail={**detail, "ok": False, "cause": cause, "requests": http.requests,
                                               "latency_ms": round((time.perf_counter() - t0) * 1000)}, commit=False)
        raise IntegrationFailed(_public(e, label), cause) from None
    log_event(db, "integration.called", actor=actor, tenant_id=inst.tenant_id, target=str(inst.id),
              detail={**detail, "ok": True, "records": len(records), "requests": http.requests,
                      "latency_ms": round((time.perf_counter() - t0) * 1000)}, commit=False)
    return records


def test(db: Session, inst: Integration, c: Connector, timeout: float = 15) -> tuple[bool, str]:
    """(ok, detail) for the admin: a public message on failure, never secrets or reply bodies."""
    secrets = secrets_of(inst)
    ctx, _ = _context(inst, c, secrets, timeout)
    try:
        return True, str(c.test_connection(ctx))[:200]
    except ConnectorError as e:
        return False, _redact(str(e), secrets)[:300]
    except Exception:  # noqa: BLE001
        _log.exception("integration test %s (%s) failed", inst.id, inst.plugin)
        return False, f"{c.manifest.label}: the plugin failed (see the API logs)"
