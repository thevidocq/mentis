"""Export and import of the platform configuration as JSON.

What travels: platform settings (SMTP, embedding, retention, syslog), AI providers and tenants
(name, status, settings, chosen LLM by provider name).
What never travels: secrets (passwords, API keys), users, documents, chats, logs.
Use it to move a configuration between lab and production or to keep it under version control;
use backup.sh for disaster recovery.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.models import LlmProvider, PlatformSetting, Tenant
from app.models.base import utcnow
from app.models.tenant import DEFAULT_TENANT_SETTINGS
from app.services import retention, syslog
from app.services import tenants as tenant_svc

FORMAT = "mentis-config/1"
_PROVIDER_FIELDS = ("kind", "base_url", "model", "options", "is_default")


class ImportError_(ValueError):
    pass


def _setting(db: Session, key: str) -> dict:
    row = db.get(PlatformSetting, key)
    return dict(row.value) if row else {}


def export_config(db: Session, tenant_ids: set | None = None) -> dict:
    providers = list(db.scalars(select(LlmProvider).order_by(LlmProvider.name)))
    by_id = {str(p.id): p.name for p in providers}
    smtp = {k: v for k, v in _setting(db, "smtp").items() if not k.endswith("_enc")}
    emb = {k: v for k, v in _setting(db, "embedding").items() if k in ("url", "model")}
    ret = {k: v for k, v in retention.get_config(db).items() if k in ("chats_days", "logs_days")}
    tenants = []
    for t in db.scalars(select(Tenant).order_by(Tenant.is_global.desc(), Tenant.name)):
        if tenant_ids is not None and t.id not in tenant_ids:
            continue
        s = dict(t.settings or {})
        tenants.append({
            "name": t.name, "general": t.is_global, "status": t.status,
            "settings": {k: s.get(k, v) for k, v in DEFAULT_TENANT_SETTINGS.items()},
            "llm": by_id.get(str(s.get("llm_provider_id"))) if s.get("llm_provider_id") else None,
            "llm_fallback": by_id.get(str(s.get("llm_fallback_id"))) if s.get("llm_fallback_id") else None,
        })
    data = {"format": FORMAT, "mentis_version": __version__, "exported_at": utcnow().isoformat(), "tenants": tenants}
    if tenant_ids is None:
        data["platform"] = {"smtp": smtp, "embedding": emb, "retention": ret, "syslog": syslog.get_config(db)}
        data["llm_providers"] = [{"name": p.name, **{f: getattr(p, f) for f in _PROVIDER_FIELDS}} for p in providers]
    return data


def _check(data: dict) -> None:
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise ImportError_("Not a Mentis configuration file (format mentis-config/1 expected).")
    if not isinstance(data.get("tenants", []), list) or not isinstance(data.get("llm_providers", []), list):
        raise ImportError_("tenants and llm_providers must be lists.")
    platform = data.get("platform") or {}
    if not isinstance(platform, dict) or any(not isinstance(platform.get(k, {}), dict)
                                             for k in ("smtp", "embedding", "syslog", "retention")):
        raise ImportError_("The platform section is malformed.")
    if "retention" in platform:
        for k in ("chats_days", "logs_days"):
            v = platform["retention"].get(k)
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= retention.MAX_DAYS:
                raise ImportError_(f"Retention {k} must be a number of days between 0 and {retention.MAX_DAYS}.")
    for t in data.get("tenants", []):
        if not isinstance(t, dict) or not str(t.get("name", "")).strip():
            raise ImportError_("Every tenant needs a name.")
        if len(str(t["name"]).strip()) < 2 or len(str(t["name"]).strip()) > 120:
            raise ImportError_(f"Tenant {t['name']}: the name must be 2 to 120 characters.")
        if t.get("settings") is not None and not isinstance(t["settings"], dict):
            raise ImportError_(f"Tenant {t['name']}: settings must be an object.")
        if t.get("status", "active") not in tenant_svc.STATUSES:
            raise ImportError_(f"Tenant {t['name']}: unknown status.")
        for k, v in (t.get("settings") or {}).items():
            if k not in DEFAULT_TENANT_SETTINGS or not isinstance(v, bool):
                raise ImportError_(f"Tenant {t['name']}: unknown or invalid setting {k}.")
    from app.services.llm import KINDS

    for p in data.get("llm_providers", []):
        if not isinstance(p, dict) or not p.get("name") or p.get("kind") not in KINDS or not p.get("base_url") or not p.get("model"):
            raise ImportError_("Every AI provider needs name, a known kind, base_url and model.")
        if not isinstance(p.get("options", {}), dict):
            raise ImportError_(f"AI provider {p['name']}: options must be an object.")


def import_config(db: Session, data: dict, apply: bool) -> list[str]:
    """Merge the file into this installation. Returns the planned (or applied) changes.

    Nothing is deleted: tenants and providers missing from the file are left as they are.
    """
    _check(data)
    plan: list[str] = []
    platform = data.get("platform") or {}

    for key, label in (("smtp", "Email (SMTP)"), ("embedding", "Embedding"), ("syslog", "Syslog forwarding")):
        if key in platform:
            incoming = {k: v for k, v in platform[key].items() if not k.endswith("_enc")}
            current = syslog.get_config(db) if key == "syslog" else _setting(db, key)
            if any(current.get(k) != v for k, v in incoming.items()):
                plan.append(f"Update {label} settings")
                if apply:
                    row = db.get(PlatformSetting, key)
                    merged = {**current, **incoming}
                    if row is None:
                        db.add(PlatformSetting(key=key, value=merged))
                    else:
                        row.value = merged
    if "retention" in platform:
        r = platform["retention"]
        cur = retention.get_config(db)
        if (r.get("chats_days"), r.get("logs_days")) != (cur["chats_days"], cur["logs_days"]):
            plan.append(f"Set retention: chats {r.get('chats_days')} days, logs {r.get('logs_days')} days")
            if apply:
                cur.update(chats_days=int(r["chats_days"]), logs_days=int(r["logs_days"]))
                row = db.get(PlatformSetting, retention.KEY)
                if row is None:
                    db.add(PlatformSetting(key=retention.KEY, value=cur))
                else:
                    row.value = cur

    existing = {p.name: p for p in db.scalars(select(LlmProvider))}
    for p in data.get("llm_providers", []):
        cur = existing.get(p["name"])
        fields = {f: p[f] for f in _PROVIDER_FIELDS if f in p and f != "is_default"}
        if cur is None:
            plan.append(f"Add AI provider {p['name']} (API key to enter after import)")
            if apply:
                cur = LlmProvider(name=p["name"], **fields)
                db.add(cur)
                existing[p["name"]] = cur
        elif any(getattr(cur, f) != v for f, v in fields.items()):
            plan.append(f"Update AI provider {p['name']}")
            if apply:
                for f, v in fields.items():
                    setattr(cur, f, v)
    if apply:
        db.flush()
    default = next((p["name"] for p in data.get("llm_providers", []) if p.get("is_default")), None)
    if default and default in existing and not existing[default].is_default:
        plan.append(f"Make {default} the default AI provider")
        if apply:
            for p in existing.values():
                p.is_default = p.name == default

    tenants = {t.name.lower(): t for t in db.scalars(select(Tenant))}
    for t in data.get("tenants", []):
        name = t["name"].strip()
        cur = tenants.get(name.lower())
        if t.get("general"):
            cur = next((x for x in tenants.values() if x.is_global), None)
        settings = {**DEFAULT_TENANT_SETTINGS, **(t.get("settings") or {})}
        for key, field in (("llm", "llm_provider_id"), ("llm_fallback", "llm_fallback_id")):
            ref = t.get(key)
            if ref and ref not in existing:
                plan.append(f"Tenant {name}: AI provider {ref} not found, keeping the current choice")
            elif ref and apply:
                settings[field] = str(existing[ref].id)
            elif not ref:
                settings[field] = None
        if cur is None:
            plan.append(f"Create tenant {name} ({t.get('status', 'active')})")
            if apply:
                cur = Tenant(name=name, slug=tenant_svc.unique_slug(db, name), status=t.get("status", "active"))
                db.add(cur)
                db.flush()
                tenants[name.lower()] = cur
        else:
            names = {str(p.id): n for n, p in existing.items()}
            cs = cur.settings or {}
            changed = (not cur.is_global and cur.status != t.get("status", cur.status)) or any(
                cs.get(k, DEFAULT_TENANT_SETTINGS[k]) != settings[k] for k in DEFAULT_TENANT_SETTINGS) or (
                names.get(str(cs.get("llm_provider_id"))) != t.get("llm") or names.get(str(cs.get("llm_fallback_id"))) != t.get("llm_fallback"))
            if changed:
                plan.append(f"Update tenant {cur.name}")
        if apply and cur is not None:
            if not cur.is_global:
                cur.status = t.get("status", cur.status)
            merged = {**(cur.settings or {}), **{k: v for k, v in settings.items() if k in DEFAULT_TENANT_SETTINGS}}
            for field in ("llm_provider_id", "llm_fallback_id"):
                if field in settings and (settings[field] is None or isinstance(settings[field], str)):
                    if settings[field] is None:
                        merged.pop(field, None)
                    else:
                        merged[field] = settings[field]
            cur.settings = merged
    if apply:
        db.commit()
        syslog.forwarder.reload(None)
    return plan
