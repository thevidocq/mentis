"""Live data for one chat question: plan, run, convert to passages. Failures never stop the
answer: they come back as short public notes shown under it."""

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.models import Chat, Tenant, User
from app.services import llm
from app.services.integrations import planner
from app.services.integrations.instances import IntegrationFailed, for_chat, run
from app.services.integrations.passages import IntegrationPassage, to_passages

_log = logging.getLogger("mentis.integrations")

MAX_LIVE_PASSAGES = 10


@dataclass
class Live:
    passages: list[IntegrationPassage] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)   # public: "ServiceNow (Acme) timed out"
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def gather(db: Session, chat: Chat, question: str, context: str, primary: dict | None, fallback: dict | None) -> Live:
    items = for_chat(db, chat)
    out = Live()
    if not items:
        return out
    tenant = db.get(Tenant, chat.scope_tenant_id)
    actor = db.get(User, chat.user_id)
    calls = planner.by_match(question, items)
    try:
        plan = planner.by_model(question, context, items, primary, fallback, done=calls)
    except llm.LLMError as e:
        _log.warning("integration planner not available: %s", e)
        plan = planner.Plan([])
    except Exception:  # noqa: BLE001 - the planner must never break the answer
        _log.exception("integration planner failed")
        plan = planner.Plan([])
    calls = [*calls, *plan.calls][:planner.MAX_CALLS]
    out.input_tokens, out.output_tokens = plan.input_tokens, plan.output_tokens
    for call in calls:
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
