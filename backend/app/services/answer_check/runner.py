"""Answer check in the chat flow: before the answer is saved (level 1, and level 2 in "hide"
mode) and after it (level 2 in "warn" mode, as a background task)."""

import logging
import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Chat, ChatMessage, Tenant
from app.services import answer_check, llm
from app.services.llm_config import checker_for
from app.services.logs import log_event

_log = logging.getLogger("mentis.answer_check")

HIDDEN_TEXT = ("Not found in {target}. An answer was written but did not match the sources, so it is not shown. "
               "Check the documents or ask in another way.")


def _tenant(db: Session, chat: Chat) -> Tenant | None:
    return db.get(Tenant, chat.scope_tenant_id) if chat.scope_tenant_id else None


def _checker_ref(cfg: dict | None) -> dict | None:
    return {"name": cfg["name"], "model": cfg["model"]} if cfg else None


def _run_level2(cfg: dict | None, result) -> tuple[list[dict], str, object]:
    """(issues, level2 state, verdict or None)."""
    if cfg is None:
        return [], "unavailable", None
    try:
        issues, verdict = answer_check.level2(cfg, result.content, result.passage_texts)
        return issues, "ok", verdict
    except llm.LLMError as e:
        _log.warning("answer check (level 2) not available: %s", e)
        return [], "unavailable", None


def _log_check(db: Session, chat: Chat, check: dict, cfg: dict | None, verdict, mode: str, commit: bool = True) -> None:
    levels = sorted({lv for i in check["issues"] for lv in i["level"]})
    log_event(db, "chat.checked", kind="system", level="warning" if check["issues"] else "info",
              tenant_id=chat.scope_tenant_id, target=str(chat.id),
              detail={"mode": mode, "level2": check["level2"], "issues": len(check["issues"]), "found_by": levels,
                      "hidden": check.get("hidden", False), "provider": cfg["name"] if cfg and verdict else None,
                      "model": cfg["model"] if cfg and verdict else None,
                      "input_tokens": getattr(verdict, "input_tokens", 0), "output_tokens": getattr(verdict, "output_tokens", 0),
                      "latency_ms": getattr(verdict, "latency_ms", None)}, commit=commit)


def before_save(db: Session, chat: Chat, question: str, first: bool, result, regenerate: Callable[[str], object]):
    """Returns (result to save, check, run level 2 later?). Only answers with status ok are checked."""
    if result.status != "ok":
        return result, None, False
    tenant = _tenant(db, chat)
    mode = answer_check.mode_of(tenant.settings if tenant else None)
    cfg = checker_for(db, tenant, result.used) if mode != "off" else None
    l1 = answer_check.level1(result.content, result.citations, result.passage_texts)
    if mode == "off":
        check = {"level2": "off", "issues": l1, "checker": None}
        _log_check(db, chat, check, None, None, mode, commit=False)
        return result, check, False
    if mode == "warn":
        return result, {"level2": "pending", "issues": l1, "checker": _checker_ref(cfg)}, True

    # "hide": check now; a failing answer is written again once, then hidden.
    l2, state, verdict = _run_level2(cfg, result)
    issues = answer_check.merge(l1, l2)
    if issues:
        problems = "; ".join(i["text"] or "no sources cited" for i in issues)[:600]
        second = regenerate(problems)
        if second.status == "ok":
            l1b = answer_check.level1(second.content, second.citations, second.passage_texts)
            l2b, state, verdict = _run_level2(cfg, second)
            issues_b = answer_check.merge(l1b, l2b)
            if not issues_b:
                check = {"level2": state, "issues": [], "checker": _checker_ref(cfg), "rewritten": True}
                _log_check(db, chat, check, cfg, verdict, mode, commit=False)
                return second, check, False
            issues = issues_b
            result = second
        hidden = result.content
        target = "the documentation of " + (tenant.name if tenant else "your customers")
        result.status, result.content = "not_found", HIDDEN_TEXT.format(target=target)
        result.citations, result.followups = [], []
        check = {"level2": state, "issues": [{k: v for k, v in i.items() if k in ("level", "kind")} for i in issues],
                 "checker": _checker_ref(cfg), "hidden": True, "hidden_answer": hidden}
        _log_check(db, chat, check, cfg, verdict, mode, commit=False)
        return result, check, False
    check = {"level2": state, "issues": [], "checker": _checker_ref(cfg)}
    _log_check(db, chat, check, cfg, verdict, mode, commit=False)
    return result, check, False


def after_save(message_id: uuid.UUID, chat_id: uuid.UUID, result) -> None:
    """Level 2 of an answer already shown ("warn"): runs after the response, in its own session."""
    db = next(get_db())
    try:
        msg, chat = db.get(ChatMessage, message_id), db.get(Chat, chat_id)
        if msg is None or chat is None or not msg.check:
            return
        cfg = checker_for(db, _tenant(db, chat), result.used)
        l2, state, verdict = _run_level2(cfg, result)
        check = {**msg.check, "level2": state, "issues": answer_check.merge(msg.check.get("issues") or [], l2)}
        msg.check = check
        db.commit()
        _log_check(db, chat, check, cfg, verdict, "warn")
    except Exception:  # noqa: BLE001 - a failed check must never break the chat
        _log.exception("answer check failed")
        db.rollback()
        msg = db.get(ChatMessage, message_id)
        if msg is not None and msg.check:
            msg.check = {**msg.check, "level2": "unavailable"}
            db.commit()
    finally:
        db.close()
