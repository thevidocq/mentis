"""Live data for one chat question: plan, run, convert to passages. Failures never stop the
answer: they come back as short public notes shown under it."""

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import Chat, Tenant, User
from app.services import llm
from app.services.integrations import planner, tool_loop
from app.services.integrations.instances import IntegrationFailed, for_chat, run
from app.services.integrations.passages import IntegrationPassage, to_passages
from app.services.logs import log_event

_log = logging.getLogger("mentis.integrations")

MAX_LIVE_PASSAGES = 10


@dataclass
class Live:
    passages: list[IntegrationPassage] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # public: "ServiceNow (Acme) timed out"
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


MODES = ("standard", "tools")


def mode_of(settings: dict | None) -> str:
    """Per customer: "standard" (one planned round, every provider) or "tools" (function calling).

    Function calling chosen by a tenant admin holds only while that admin still chooses the LLM
    (the customer's own LLM, and tenant admins allowed to set it): otherwise it is standard again."""
    s = settings or {}
    m = s.get("integration_mode")
    if m not in MODES:
        return "standard"
    if m == "tools" and s.get("integration_mode_by") == "tenant_admin" and not (
            s.get("llm_provider_id") and s.get("admin_can_set_llm", True)):
        return "standard"
    return m


def gather(db: Session, chat: Chat, question: str, context: str, primary: dict | None, fallback: dict | None) -> Live:
    items = for_chat(db, chat)
    if not items:
        return Live()
    tenant = db.get(Tenant, chat.scope_tenant_id)
    actor = db.get(User, chat.user_id)
    pre = None
    if mode_of(tenant.settings) == "tools":
        try:
            return _with_tools(db, chat, tenant, actor, question, context, items, primary or fallback)
        except tool_loop.ToolsUnavailable as e:
            # The model or provider does not do tool calling: the standard mode, without reading again.
            log_event(db, "integration.tools_unavailable", kind="system", level="warning", tenant_id=tenant.id,
                      target=str(chat.id), detail={"provider": (primary or fallback or {}).get("name"), "cause": str(e)[:300]},
                      commit=False)
            pre = e.gathered
        except Exception:  # noqa: BLE001 - never break the answer
            _log.exception("tool lookups failed")
    return _standard(db, chat, tenant, actor, question, context, items, primary, fallback, pre)


def _log_usage(db: Session, chat: Chat, mode: str, provider: str | None, model: str | None, tokens_in: int, tokens_out: int,
               calls: int, latency_ms: int | None = None, rounds: int | None = None) -> None:
    if provider:  # LLM usage: "<provider> · integration lookups" (metadata only)
        log_event(db, "integration.planned", kind="system", tenant_id=chat.scope_tenant_id, target=str(chat.id),
                  detail={"mode": mode, "provider": provider, "model": model, "input_tokens": tokens_in,
                          "output_tokens": tokens_out, "latency_ms": latency_ms, "calls": calls, "rounds": rounds},
                  commit=False)


def _with_tools(db, chat, tenant, actor, question, context, items, cfg) -> Live:
    g = tool_loop.gather(db, chat, question, context, items, cfg, actor)
    _log_usage(db, chat, "tools", g.provider, g.model, g.input_tokens, g.output_tokens, g.calls, rounds=g.rounds)
    out = Live(notes=g.notes, calls=g.calls, input_tokens=g.input_tokens, output_tokens=g.output_tokens)
    seen = set()
    for inst, c, records in g.records:
        for p in to_passages(tenant, inst, c, records):
            key = (p.integration_id, p.record_kind, p.record_id)
            if key not in seen:
                seen.add(key)
                out.passages.append(p)
    out.passages = out.passages[:MAX_LIVE_PASSAGES]
    return out


def _standard(db, chat, tenant, actor, question, context, items, primary, fallback, pre=None) -> Live:
    out = Live()
    if pre is not None:  # read already by the tools mode before it gave up
        calls = list(pre.matched)
        out.notes, out.calls = list(pre.notes), pre.calls
        for inst, c, records in pre.records:
            out.passages += to_passages(tenant, inst, c, records)
    else:
        calls = planner.by_match(question, items)
    try:
        plan = planner.by_model(question, context, items, primary, fallback, done=calls)
    except llm.LLMError as e:
        _log.warning("integration planner not available: %s", e)
        plan = planner.Plan([])
    except Exception:  # noqa: BLE001 - the planner must never break the answer
        _log.exception("integration planner failed")
        plan = planner.Plan([])
    to_run = plan.calls if pre is not None else [*calls, *plan.calls]
    to_run = to_run[:max(planner.MAX_CALLS - out.calls, 0)]
    out.input_tokens, out.output_tokens = plan.input_tokens, plan.output_tokens
    _log_usage(db, chat, "standard", plan.provider, plan.model, plan.input_tokens, plan.output_tokens, len(plan.calls), plan.latency_ms)
    for call in to_run:
        out.calls += 1
        try:
            records = run(db, call.integration, call.connector, call.operation.name, call.args,
                          actor=actor, chat_id=chat.id, purpose=f"chat:{call.how}")
        except IntegrationFailed as e:
            out.notes.append(e.public)
            continue
        if not records:
            what = ", ".join(call.args.values())
            out.notes.append(f"{call.connector.manifest.label} ({call.integration.name}): nothing found for {what}"[:200])
        out.passages += to_passages(tenant, call.integration, call.connector, records)
    out.passages = out.passages[:MAX_LIVE_PASSAGES]
    out.notes = list(dict.fromkeys(out.notes))
    return out
