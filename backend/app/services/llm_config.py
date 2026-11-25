"""Which providers answer for a tenant: its own choice, else the platform default; plus an optional fallback."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import LlmProvider, Tenant
from app.services.llm import provider_config


def default_provider(db: Session) -> LlmProvider | None:
    return db.scalar(select(LlmProvider).where(LlmProvider.is_default.is_(True)))


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
