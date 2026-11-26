"""Which providers answer for a tenant: its own choice, else the platform default; plus an optional fallback."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LlmProvider, Tenant
from app.services.llm import KINDS, provider_config

OPTION_KEYS = {"reasoning_effort", "max_tokens", "price_in", "price_out", "temperature"}


def provider_problem(kind, base_url, options) -> str | None:
    """Why a provider definition is invalid, or None. Shared by the AI providers page and config import."""
    if kind not in KINDS:
        return "Unknown provider type."
    if not isinstance(base_url, str) or not base_url.startswith(("http://", "https://")):
        return "The URL must start with http:// or https://."
    if not isinstance(options, dict):
        return "Options must be an object."
    if options.get("reasoning_effort") not in (None, "", "minimal", "low", "medium", "high"):
        return "Reasoning effort must be minimal, low, medium or high."
    for k in ("price_in", "price_out"):
        v = options.get(k)
        if v is not None and (not isinstance(v, int | float) or isinstance(v, bool) or not 0 <= v <= 1000):
            return "Prices are USD per million tokens, between 0 and 1000."
    unknown = set(options) - OPTION_KEYS
    if unknown:
        return f"Unknown options: {', '.join(sorted(unknown))}."
    t = options.get("temperature")
    if t is not None and (not isinstance(t, int | float) or isinstance(t, bool) or not 0 <= t <= 2):
        return "Temperature must be between 0 and 2."
    mt = options.get("max_tokens")
    if mt is not None and (not isinstance(mt, int) or isinstance(mt, bool) or not 100 <= mt <= 16000):
        return "Max tokens must be between 100 and 16000."
    return None


def same_origin(a: str | None, b: str | None) -> bool:
    """Same scheme, host and port. A stored API key is only ever sent to the origin it was saved for."""
    from urllib.parse import urlsplit

    try:
        ua, ub = urlsplit((a or "").strip()), urlsplit((b or "").strip())
        return (ua.scheme.lower(), ua.hostname, ua.port) == (ub.scheme.lower(), ub.hostname, ub.port) and bool(ua.hostname)
    except ValueError:
        return False


ANSWERS, CHECKER = "answers", "checker"


def default_provider(db: Session, role: str = ANSWERS) -> LlmProvider | None:
    return db.scalar(select(LlmProvider).where(LlmProvider.is_default.is_(True), LlmProvider.role == role))


def checker_for(db: Session, tenant: Tenant | None, answered_by: dict | None) -> dict | None:
    """Model that checks an answer (level 2):
    1. the checker chosen for this customer;
    2. a customer with its own LLM: that LLM (its data stays with the provider the customer chose);
    3. the platform's default checker;
    4. the model that wrote the answer."""
    s = (tenant.settings or {}) if tenant else {}
    chosen = _get(db, s.get("checker_provider_id"))
    if chosen is not None:
        return provider_config(chosen)
    own = _get(db, s.get("llm_provider_id"))
    if own is not None:
        return provider_config(own)
    default = default_provider(db, CHECKER)
    if default is not None:
        return provider_config(default)
    return answered_by


def _get(db: Session, pid) -> LlmProvider | None:
    try:
        return db.get(LlmProvider, uuid.UUID(str(pid))) if pid else None
    except ValueError:
        return None


def providers_for(db: Session, tenant: Tenant | None) -> tuple[dict | None, dict | None]:
    """(primary, fallback) configs. tenant=None ("All customers") uses the platform default."""
    s = (tenant.settings or {}) if tenant else {}
    primary = _get(db, s.get("llm_provider_id")) or default_provider(db)
    fallback = _get(db, s.get("llm_fallback_id"))
    if fallback is not None and primary is not None and fallback.id == primary.id:
        fallback = None
    return (provider_config(primary) if primary else None, provider_config(fallback) if fallback else None)
