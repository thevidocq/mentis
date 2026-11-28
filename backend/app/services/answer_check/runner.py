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


def _checker(db: Session, tenant: Tenant | None, used: dict | None) -> dict | None:
    """The checker model for this customer, with the customer's token limit for the check."""
    cfg = checker_for(db, tenant, used)
    limit = (tenant.settings or {}).get("check_max_tokens") if tenant else None
    return {**cfg, "check_max_tokens": limit} if cfg and limit else cfg


def _checker_ref(cfg: dict | None) -> dict | None:
    return {"name": cfg["name"], "model": cfg["model"]} if cfg else None


def _run_level2(cfg: dict | None, result) -> tuple[list[dict], str, object]:
    """(issues, level2 state, verdict or None)."""
    if cfg is None:
        return [], "unavailable", None
    try:
        issues, verdict = answer_check.level2(cfg, result.content, result.passage_texts)
        # "Matches the sources" needs the checker to have read the answer: with nothing it could
        # check against, the answer is not verified.
        return issues, "ok" if verdict.checked else "unavailable", verdict
    except llm.LLMError as e:
        _log.warning("answer check (level 2) not available: %s", e)
        return [], "unavailable", None
    except Exception:  # noqa: BLE001 - a broken check must never break the chat
        _log.exception("answer check (level 2) failed")
        return [], "unavailable", None


def _unchecked(verdict) -> dict:
    """Statements of a very long answer the checker never saw: shown, never reported as matching."""
    n = getattr(verdict, "unchecked", 0)
    return {"unchecked": n} if n else {}


def _too_long(verdict) -> list[dict]:
    return [{"level": [2], "kind": "unchecked", "text": ""}] if getattr(verdict, "unchecked", 0) else []


def _problem(issue: dict) -> str:
    """One issue as the model should read it, with the reason, so the second answer fixes it. The
    quoted text comes from the draft and the checker: neutralised like passages (prompts.data_text)."""
    from app.services.prompts import data_text

    kind, text = issue.get("kind"), data_text(issue.get("text") or "")
    issue = {**issue, "reason": data_text(issue["reason"]) if issue.get("reason") else issue.get("reason")}
    if kind == "value":
        return f'the value "{text}" is not in the passages it cites'
    if kind == "uncited":
        return f'"{text}" has no citation'
    if kind == "no_citations":
        return "the answer cites no passage"
    if kind == "unchecked":
        return "the answer has more statements than can be checked: answer more briefly"
    return f'"{text}" is not supported by its cited passages' + (f" ({issue['reason']})" if issue.get("reason") else "")


def _run_level1(result) -> list[dict]:
    try:
        issues = answer_check.level1(result.content, result.citations, result.passage_texts)
        if getattr(result, "cut", False):
            # The last statement of an answer cut by the token limit lost its citation to the cut, not
            # to the model: flagging it would blame the sources (the answer already says it was cut).
            units = answer_check.units.split(result.content)
            last = units[-1].raw if units else None
            issues = [i for i in issues if not (i["kind"] == "uncited" and i["text"] == last)]
        return issues
    except Exception:  # noqa: BLE001 - same: level 1 is pure code, but never trusted to be bug-free
        _log.exception("answer check (level 1) failed")
        return []


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
    cfg = _checker(db, tenant, result.used) if mode != "off" else None
    l1 = _run_level1(result)
    if mode == "off":
        check = {"level2": "off", "issues": l1, "checker": None}
        _log_check(db, chat, check, None, None, mode, commit=False)
        return result, check, False
    if mode == "warn":
        return result, {"level2": "pending", "issues": l1, "checker": _checker_ref(cfg)}, True

    # "hide": check now; a failing answer is written again once, then hidden. Statements the checker
    # could not read (a very long answer) count as a failure: hide mode shows only checked answers.
    l2, state, verdict = _run_level2(cfg, result)
    issues = answer_check.merge(l1, l2) + _too_long(verdict)
    if issues:
        problems = "; ".join(_problem(i) for i in issues)[:900]
        try:
            second = regenerate(problems)
        except Exception:  # noqa: BLE001 - no second answer: the first one stays hidden
            _log.warning("answer check: rewriting the answer failed", exc_info=True)
            second = None
        if second is not None and second.status == "ok":
            l1b = _run_level1(second)
            l2b, state, verdict = _run_level2(cfg, second)
            issues_b = answer_check.merge(l1b, l2b) + _too_long(verdict)
            if not issues_b:
                check = {"level2": state, "issues": [], "checker": _checker_ref(cfg), "rewritten": True, **_unchecked(verdict)}
                _log_check(db, chat, check, cfg, verdict, mode, commit=False)
                return second, check, False
            issues = issues_b
            result = second
        hidden = result.content
        target = "the documentation of " + (tenant.name if tenant else "your customers")
        result.status, result.content = "not_found", HIDDEN_TEXT.format(target=target)
        result.citations, result.followups = [], []
        result.title = None  # the hidden draft must not name the chat either (the question does)
        check = {"level2": state, "issues": [{k: v for k, v in i.items() if k in ("level", "kind")} for i in issues],
                 "checker": _checker_ref(cfg), "hidden": True, "hidden_answer": hidden}
        _log_check(db, chat, check, cfg, verdict, mode, commit=False)
        return result, check, False
    check = {"level2": state, "issues": [], "checker": _checker_ref(cfg), **_unchecked(verdict)}
    _log_check(db, chat, check, cfg, verdict, mode, commit=False)
    return result, check, False


def after_save(message_id: uuid.UUID, chat_id: uuid.UUID, result) -> None:
    """Level 2 of an answer already shown ("warn"): runs after the response, in its own session."""
    db = next(get_db())
    try:
        msg, chat = db.get(ChatMessage, message_id), db.get(Chat, chat_id)
        if msg is None or chat is None or not msg.check:
            return
        cfg = _checker(db, _tenant(db, chat), result.used)
        content = msg.content
        db.rollback()  # no transaction is held while the checker runs (it may take minutes)
        l2, state, verdict = _run_level2(cfg, result)
        # Read the message again, locked: it may have been removed meanwhile (a source deleted). Its
        # current check is the base; a removed answer keeps no issue quoting its old text.
        msg = db.get(ChatMessage, message_id, with_for_update=True, populate_existing=True)
        if msg is None or not msg.check or msg.check.get("redacted") or msg.content != content:
            db.rollback()
            return
        check = {**msg.check, "level2": state, "issues": answer_check.merge(msg.check.get("issues") or [], l2),
                 **_unchecked(verdict)}
        msg.check = check
        db.commit()
        _log_check(db, chat, check, cfg, verdict, "warn")
    except Exception:  # noqa: BLE001 - a failed check must never break the chat
        _log.exception("answer check failed")
        db.rollback()
        msg = db.get(ChatMessage, message_id, with_for_update=True, populate_existing=True)
        if msg is not None and msg.check and not msg.check.get("redacted"):
            msg.check = {**msg.check, "level2": "unavailable"}
            db.commit()
    finally:
        db.close()
