"""Export and import of the platform configuration as JSON.

What travels: platform settings (SMTP, embedding, retention, syslog), AI providers and tenants
(name, status, settings, chosen LLM by provider name).
What never travels: secrets (passwords, API keys), users, documents, chats, logs.
Use it to move a configuration between lab and production or to keep it under version control;
use backup.sh for disaster recovery.
"""

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.models import LlmProvider, PlatformSetting, Tenant
from app.models.base import utcnow
from app.models.tenant import DEFAULT_TENANT_SETTINGS
from app.services import llm_config, mail, retention, syslog
from app.services import tenants as tenant_svc

FORMAT = "mentis-config/1"
_PROVIDER_FIELDS = ("kind", "base_url", "model", "options", "is_default", "role")
# Platform settings that travel, per section. Anything else in a file (secrets, the embedding
# model the index was built with, keys of a newer version) is ignored.
_PLATFORM_KEYS = {
    "smtp": ("host", "port", "security", "username", "from_address"),
    "embedding": ("url", "model"),
    "syslog": tuple(syslog.DEFAULTS),
}


def _int_in(v, lo: int, hi: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _str_max(v, n: int) -> bool:
    return isinstance(v, str) and len(v) <= n


# The same limits as the settings pages, so an imported value cannot break sending or forwarding.
_VALID = {
    "smtp": {
        "host": lambda v: _str_max(v, 255), "port": lambda v: _int_in(v, 1, 65535),
        "security": lambda v: v in mail.SECURITY_MODES, "username": lambda v: _str_max(v, 255),
        "from_address": lambda v: _str_max(v, 320),
    },
    "embedding": {
        "url": lambda v: _str_max(v, 500) and v.startswith(("http://", "https://")),
        "model": lambda v: _str_max(v, 200) and bool(v.strip()),
    },
    "syslog": {
        "enabled": lambda v: isinstance(v, bool), "host": lambda v: _str_max(v, 253),
        "port": lambda v: _int_in(v, 1, 65535), "protocol": lambda v: v in syslog.PROTOCOLS,
        "verify_tls": lambda v: isinstance(v, bool),
        "app_name": lambda v: isinstance(v, str) and re.fullmatch(r"[!-~]{1,48}", v) is not None,
    },
}


def _incoming(platform: dict, key: str) -> dict:
    return {k: v for k, v in platform[key].items() if k in _PLATFORM_KEYS[key]}


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
    ret = {k: v for k, v in retention.get_config(db).items() if k in ("chats_days", "logs_days", "versions_keep")}
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
            "checker": by_id.get(str(s.get("checker_provider_id"))) if s.get("checker_provider_id") else None,
            "answer_check": s.get("answer_check", "warn"),
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
    for key, checks in _VALID.items():
        if key in platform:
            for k, v in _incoming(platform, key).items():
                if not checks[k](v):
                    raise ImportError_(f"The {key} setting {k} is invalid.")
    if "retention" in platform:
        for k in ("chats_days", "logs_days"):
            v = platform["retention"].get(k)
            if not isinstance(v, int) or isinstance(v, bool) or not 0 <= v <= retention.MAX_DAYS:
                raise ImportError_(f"Retention {k} must be a number of days between 0 and {retention.MAX_DAYS}.")
        vk = platform["retention"].get("versions_keep", 0)  # optional: files exported before 0.3.5 lack it
        if not isinstance(vk, int) or isinstance(vk, bool) or not 0 <= vk <= retention.MAX_VERSIONS:
            raise ImportError_(f"Retention versions_keep must be between 0 and {retention.MAX_VERSIONS}.")
    for t in data.get("tenants", []):
        if not isinstance(t, dict) or not isinstance(t.get("name"), str) or not t["name"].strip():
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
        if (not isinstance(p, dict) or not _str_max(p.get("name"), 80) or not p["name"].strip()
                or p.get("kind") not in KINDS or not _str_max(p.get("base_url"), 500)
                or not _str_max(p.get("model"), 200) or not p["model"].strip()):
            raise ImportError_("Every AI provider needs name, a known kind, base_url and model.")
        if not isinstance(p.get("options", {}), dict):
            raise ImportError_(f"AI provider {p['name']}: options must be an object.")
        problem = llm_config.provider_problem(p["kind"], p["base_url"], p.get("options", {}))
        if problem:
            raise ImportError_(f"AI provider {p['name']}: {problem}")
        if not isinstance(p.get("is_default", False), bool):
            raise ImportError_(f"AI provider {p['name']}: is_default must be true or false.")
        if p.get("role", "answers") not in ("answers", "checker"):
            raise ImportError_(f"AI provider {p['name']}: role must be answers or checker.")
    for t in data.get("tenants", []):
        if t.get("answer_check", "warn") not in ("warn", "hide", "off"):
            raise ImportError_(f"Tenant {t.get('name')}: answer_check must be warn, hide or off.")


def import_config(db: Session, data: dict, apply: bool) -> list[str]:
    """Merge the file into this installation. Returns the planned (or applied) changes.

    Nothing is deleted: tenants and providers missing from the file are left as they are.
    """
    _check(data)
    plan: list[str] = []
    platform = data.get("platform") or {}

    for key, label in (("smtp", "Email (SMTP)"), ("embedding", "Embedding"), ("syslog", "Syslog forwarding")):
        if key in platform:
            incoming = _incoming(platform, key)
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
        vk = int(r.get("versions_keep", cur.get("versions_keep", 0)))
        if (r.get("chats_days"), r.get("logs_days"), vk) != (cur["chats_days"], cur["logs_days"], cur.get("versions_keep", 0)):
            plan.append(f"Set retention: chats {r.get('chats_days')} days, logs {r.get('logs_days')} days, old versions kept {vk or 'all'}")
            if apply:
                cur.update(chats_days=int(r["chats_days"]), logs_days=int(r["logs_days"]), versions_keep=vk)
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
            moved = "base_url" in fields and cur.api_key_enc and not llm_config.same_origin(cur.base_url, fields["base_url"])
            plan.append(f"Update AI provider {p['name']}" + (" (new address: API key to enter again)" if moved else ""))
            if apply:
                if cur.is_default and fields.get("role", cur.role) != cur.role:
                    cur.is_default = False  # a default moving to the other role must not be a second default there
                for f, v in fields.items():
                    setattr(cur, f, v)
                if moved:  # the stored key is never sent to an address it was not saved for
                    cur.api_key_enc = None
    if apply:
        db.flush()
    # Providers this import adds count as existing for the plan too, so the dry run matches the apply.
    known = set(existing) | {p["name"] for p in data.get("llm_providers", [])}
    # One default per role (answers; answer check). Files exported before 0.3.6 have no role: answers.
    for role in ("answers", "checker"):
        default = next((p["name"] for p in data.get("llm_providers", []) if p.get("is_default") and p.get("role", "answers") == role), None)
        if default and default in known and not (default in existing and existing[default].is_default):
            plan.append(f"Make {default} the default {'AI provider' if role == 'answers' else 'answer checker'}")
            if apply:
                for p in existing.values():
                    if p.role == role:
                        p.is_default = p.name == default
        if apply:  # like adding one by hand: a role with models always has a default
            same = [p for p in existing.values() if p.role == role]
            if same and not any(p.is_default for p in same):
                same[0].is_default = True

    tenants = {t.name.lower(): t for t in db.scalars(select(Tenant))}
    for t in data.get("tenants", []):
        name = t["name"].strip()
        cur = tenants.get(name.lower())
        if t.get("general"):
            cur = next((x for x in tenants.values() if x.is_global), None)
        settings = {**DEFAULT_TENANT_SETTINGS, **(t.get("settings") or {})}
        for key, field in (("llm", "llm_provider_id"), ("llm_fallback", "llm_fallback_id"), ("checker", "checker_provider_id")):
            if key not in t:  # files exported before 0.3.6 have no checker: keep the current choice
                continue
            ref = t.get(key)
            if ref and ref not in known:
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
            # A key missing from the file (older export) keeps the current value.
            changed = (not cur.is_global and cur.status != t.get("status", cur.status)) or any(
                cs.get(k, DEFAULT_TENANT_SETTINGS[k]) != settings[k] for k in DEFAULT_TENANT_SETTINGS) or any(
                key in t and names.get(str(cs.get(field))) != t[key]
                for key, field in (("llm", "llm_provider_id"), ("llm_fallback", "llm_fallback_id"), ("checker", "checker_provider_id"))) or (
                "answer_check" in t and cs.get("answer_check", "warn") != t["answer_check"])
            if changed:
                plan.append(f"Update tenant {cur.name}")
        if apply and cur is not None:
            if not cur.is_global:
                cur.status = t.get("status", cur.status)
            merged = {**(cur.settings or {}), **{k: v for k, v in settings.items() if k in DEFAULT_TENANT_SETTINGS}}
            if "answer_check" in t or "answer_check" not in merged:
                merged["answer_check"] = t.get("answer_check", "warn")
            for field in ("llm_provider_id", "llm_fallback_id", "checker_provider_id"):
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
