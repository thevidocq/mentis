"""Answering a chat question: scope → retrieval → LLM → validated answer with citations."""

import json
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Chat, ChatMessage, Role, Tenant, User
from app.services import access, answer_check, chat_visibility, llm, prompts, retrieval
from app.services.llm_config import providers_for
from app.services.setup import GENERAL_NAME

HISTORY_TURNS = 6


@dataclass
class Answer:
    status: str  # ok | not_found | error
    content: str
    citations: list[dict] = field(default_factory=list)
    followups: list[str] = field(default_factory=list)
    tenants: list[str] = field(default_factory=list)
    title: str | None = None
    provider_name: str | None = None
    model: str | None = None
    latency_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    passages: int = 0
    # For the answer check (not stored): the passages given to the model, and the model that answered.
    passage_texts: dict[int, str] = field(default_factory=dict)
    used: dict | None = None


def all_label(user: User | None) -> str:
    return "All customers" if user is not None and user.all_tenants else "All my customers"


def scope_tenants(db: Session, chat: Chat) -> tuple[list[Tenant], str, Tenant | None]:
    """Tenants searched for this chat, the scope label, and the scope tenant (None = all the user's customers).

    Access is checked again on every question: a customer removed from the user is not searched.
    The General Knowledge Base is searched with the customer(s) unless the user turned it off for
    this chat or the customer turned it off in its settings.
    """
    owner = db.get(User, chat.user_id)
    if owner is None:
        return [], "Unknown customer", None
    visible = [t for t in access.tenants(db, owner) if t.status != "disabled"]
    general = next((t for t in visible if t.is_global), None)
    if chat.scope_tenant_id is None:
        customers = [t for t in visible if not t.is_global]
        return customers + ([general] if general and customers and chat.use_general else []), all_label(owner), None
    tenant = next((t for t in visible if t.id == chat.scope_tenant_id), None)
    if tenant is None:
        return [], "Unknown customer", None
    tenants = [tenant]
    if general is not None and not tenant.is_global and chat.use_general and (tenant.settings or {}).get("include_general", True):
        tenants.append(general)
    return tenants, tenant.name, tenant


def _history(db: Session, chat: Chat) -> list[ChatMessage]:
    """The last exchanges as alternating user/assistant turns.

    A question whose answer failed is dropped with it, so the model never gets two user turns in a
    row nor a conversation that starts with the assistant (some providers refuse both).
    """
    rows = db.scalars(select(ChatMessage).where(ChatMessage.chat_id == chat.id)
                      .order_by(ChatMessage.created_at.desc(), ChatMessage.role).limit(HISTORY_TURNS * 2)).all()
    rows = list(reversed(rows))
    # Answers that used a customer no longer assigned to the user never go back to the LLM.
    vis = chat_visibility.Visibility(db, db.get(User, chat.user_id))
    turns: list[ChatMessage] = []
    for q, a in zip(rows, rows[1:], strict=False):
        if q.role == "user" and a.role == "assistant" and a.status != "error" and not vis.hidden(chat, a):
            turns += [q, a]
    return turns[-HISTORY_TURNS:]


def _retrieval_query(question: str, history: list[ChatMessage]) -> str:
    # Short follow-ups ("and for medium severity?") need the previous question to find passages.
    previous = next((m.content for m in reversed(history) if m.role == "user"), None)
    return f"{previous}\n{question}" if previous and len(question.split()) <= 8 else question


def _partial_answer(text: str) -> str | None:
    """The "answer" string of a JSON reply cut short (the model hit its token limit)."""
    m = re.search(r'\{\s*"answer"\s*:\s*"((?:[^"\\]|\\.)*)', text, re.S)
    if m is None:
        return None
    raw = re.sub(r"\\(u[0-9a-fA-F]{0,3})?$", "", m.group(1))  # drop an escape cut in half
    try:
        return json.loads(f'"{raw}"', strict=False)
    except ValueError:
        return None


def _parse_json(text: str) -> dict | None:
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    for candidate in (cleaned, cleaned[cleaned.find("{"): cleaned.rfind("}") + 1] if "{" in cleaned else ""):
        try:
            # strict=False: many models put raw line breaks inside the answer string.
            data = json.loads(candidate, strict=False)
            if isinstance(data, dict) and isinstance(data.get("answer"), str):
                return data
        except (ValueError, TypeError):
            continue
    partial = _partial_answer(cleaned)
    return {"answer": partial} if partial is not None else None


def _cited(answer_text: str, passages) -> tuple[str, list[dict]]:
    """Keep [n] markers that exist, drop the others; return citations in order of first use."""
    order: list[int] = []

    def keep(m: re.Match) -> str:
        n = int(m.group(1))
        if 1 <= n <= len(passages):
            if n not in order:
                order.append(n)
            return f"[{n}]"
        return ""

    # Grouped markers ("[1, 2]") are split first, so each number is checked like a single one.
    answer_text = re.sub(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})+)\]",
                         lambda m: "".join(f"[{n.strip()}]" for n in m.group(1).split(",")), answer_text)
    text = re.sub(r"\[(\d{1,3})\]", keep, answer_text)
    citations = []
    for n in order:
        p = passages[n - 1]
        citations.append({
            "n": n, "tenant": GENERAL_NAME if p.is_general else p.tenant_name, "tenant_id": str(p.tenant_id), "is_general": p.is_general,
            "document": p.document_name, "version": p.version, "page": p.page_label, "heading": p.heading,
            "text": p.text[:600],
        })
    return text, citations


def _whose(scope_label: str) -> str:
    return "your customers'" if scope_label in ("All customers", "All my customers") else f"{scope_label}'s"


def not_found_text(scope_label: str) -> str:
    target = "the customers' documentation" if scope_label in ("All customers", "All my customers") else f"the documentation of {scope_label}"
    return f"Not found in {target}. No document in use covers this question."


def answer(db: Session, chat: Chat, question: str, first: bool, correction: str | None = None) -> Answer:
    """`correction`: problems of a first draft found by the answer check, for a second attempt."""
    tenants, scope_label, scope_tenant = scope_tenants(db, chat)
    history = _history(db, chat)
    s = get_settings()

    passages = retrieval.search_tenants(db, [t.id for t in tenants], _retrieval_query(question, history),
                                        limit=s.chat_passages, min_score=s.chat_min_score) if tenants else []
    if not passages:
        # No LLM call: nothing to ground an answer on, so nothing can be invented.
        content = not_found_text(scope_label)
        if len(question.split()) <= 2:  # "ciao", "hello", "test": explain what to ask instead
            content = (f"I answer questions about {_whose(scope_label)} procedures from the documents in use, "
                       "for example: *Who do I call for a brute-force alert?* or *What is the SLA for a critical incident?*")
        return Answer(status="not_found", content=content, tenants=[scope_label],
                      title=question[:60] if first else None)

    want_followups = (scope_tenant.settings or {}).get("suggested_followups", True) if scope_tenant else True
    system = prompts.system_prompt(followups=want_followups, title=first)
    # A flagged earlier answer goes back with a note, so its error does not spread to the next answers.
    turns = [llm.Turn(m.role, m.content + (answer_check.history_note(m.check) if m.role == "assistant" else "")) for m in history]
    message = prompts.user_message(question, passages, scope_label)
    if correction:
        message += f"\n\nA previous draft of this answer was rejected: {correction}. Answer again strictly from the passages."
    turns.append(llm.Turn("user", message))

    primary, fallback = providers_for(db, scope_tenant)
    reply, used, latency = llm.call_with_failover(primary, fallback, system, turns)

    data = _parse_json(reply.text)
    raw_answer = data["answer"] if data else reply.text.strip()
    text, citations = _cited(raw_answer, passages)
    is_not_found = bool(data and data.get("not_found")) or not text.strip()
    raw_followups = data.get("followups") if data else None
    followups = [f.strip() for f in raw_followups if isinstance(f, str) and f.strip()][:3] \
        if isinstance(raw_followups, list) and want_followups else []
    title = data.get("title") if data and isinstance(data.get("title"), str) else None

    names = list(dict.fromkeys(c["tenant"] for c in citations if not c["is_general"]))
    if any(c["is_general"] for c in citations):
        names.append(GENERAL_NAME)
    return Answer(
        status="not_found" if is_not_found else "ok",
        content=text or not_found_text(scope_label),
        citations=[] if is_not_found else citations,
        followups=[] if is_not_found else followups,
        tenants=names or [scope_label],
        title=(title or question)[:60] if first else None,
        provider_name=used["name"], model=used["model"], latency_ms=latency,
        passage_texts={i: p.text for i, p in enumerate(passages, start=1)}, used=used,
        input_tokens=reply.input_tokens, output_tokens=reply.output_tokens, passages=len(passages),
    )
