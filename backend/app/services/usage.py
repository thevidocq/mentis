"""LLM usage per customer and provider, from the chat.answered log events (metadata only).

Usage follows log retention: events older than the log retention period are gone.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, LlmProvider, Tenant


def _price(providers: dict[str, LlmProvider], name: str | None) -> tuple[float | None, float | None]:
    p = providers.get(name or "")
    if p is None:
        return None, None
    o = p.options or {}
    return o.get("price_in"), o.get("price_out")


def usage(db: Session, since: datetime, until: datetime, tenant_id: uuid.UUID | None = None, only_tenant: bool = False) -> dict:
    """Rows per (customer, provider). only_tenant=True restricts to tenant_id (tenant admins)."""
    stmt = select(AuditEvent).where(AuditEvent.action == "chat.answered", AuditEvent.ts >= since, AuditEvent.ts < until)
    if only_tenant:
        stmt = stmt.where(AuditEvent.tenant_id == tenant_id)
    names = {t.id: t.name for t in db.scalars(select(Tenant))}
    providers = {p.name: p for p in db.scalars(select(LlmProvider))}
    rows: dict[tuple, dict] = {}
    for e in db.scalars(stmt):
        d = e.detail or {}
        customer = "All customers" if e.tenant_id is None else names.get(e.tenant_id, "Deleted customer")
        key = (customer, d.get("provider") or "—")
        r = rows.setdefault(key, {"customer": customer, "tenant_id": str(e.tenant_id) if e.tenant_id else None,
                                  "provider": key[1], "questions": 0, "answered": 0, "not_found": 0, "errors": 0,
                                  "input_tokens": 0, "output_tokens": 0, "latency_total": 0, "latency_n": 0})
        r["questions"] += 1
        status = d.get("status")
        r["answered" if status == "ok" else "not_found" if status == "not_found" else "errors"] += 1
        r["input_tokens"] += d.get("input_tokens") or 0
        r["output_tokens"] += d.get("output_tokens") or 0
        if d.get("latency_ms"):
            r["latency_total"] += d["latency_ms"]
            r["latency_n"] += 1
    out = []
    for r in rows.values():
        pin, pout = _price(providers, r["provider"])
        cost = None
        if pin is not None or pout is not None:
            cost = round(r["input_tokens"] / 1e6 * (pin or 0) + r["output_tokens"] / 1e6 * (pout or 0), 4)
        n = r.pop("latency_n")
        total = r.pop("latency_total")
        out.append({**r, "avg_latency_ms": round(total / n) if n else None, "cost_usd": cost})
    out.sort(key=lambda r: (-r["questions"], r["customer"]))
    totals = {k: sum(r[k] for r in out) for k in ("questions", "answered", "not_found", "errors", "input_tokens", "output_tokens")}
    costs = [r["cost_usd"] for r in out if r["cost_usd"] is not None]
    totals["cost_usd"] = round(sum(costs), 4) if costs else None
    return {"rows": out, "totals": totals}
