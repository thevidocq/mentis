"""Answer check: is every statement of an answer in its sources?

Level 1 (values.py) always runs, at once and without a model. Level 2 (judge.py) asks a model,
chosen by llm_config.checker_for. Per customer (tenant settings "answer_check"):
- "warn" (default): the answer is shown at once; level 2 runs after it and its result is added;
- "hide": both levels run before the answer is shown; an answer that fails is written again once,
  then replaced by "Not found" (the hidden text is kept for audit, never sent to the browser);
- "off": level 2 does not run (level 1 still does).

The result is stored on the message (ChatMessage.check):
  {"level2": "pending" | "ok" | "unavailable" | "off", "issues": [...], "checker": {"name", "model"},
   "hidden": bool, "hidden_answer": str (audit only)}
Issues: {"level": [1] | [2] | [1, 2], "kind": "value" | "statement" | "no_citations", "text", "expected"?, "reason"?}
"""

from app.services.answer_check import judge as judge_mod
from app.services.answer_check import units as units_mod
from app.services.answer_check import values

MODES = ("warn", "hide", "off")
DEFAULT_MODE = "warn"
PENDING_TIMEOUT_S = 120


def mode_of(settings: dict | None) -> str:
    m = (settings or {}).get("answer_check")
    return m if m in MODES else DEFAULT_MODE


def level1(content: str, citations: list[dict], passages: dict[int, str]) -> list[dict]:
    cited = {c["n"]: passages[c["n"]] for c in citations if c.get("n") in passages}
    issues = values.check(content, cited, list(passages.values()))
    if not citations:
        issues.append({"level": [1], "kind": "no_citations", "text": ""})
    return issues


def level2(cfg: dict, content: str, passages: dict[int, str]) -> tuple[list[dict], judge_mod.Verdict]:
    """Statements the checker rejects, as issues (raises llm.LLMError when it cannot check)."""
    units = units_mod.split(content)
    verdict = judge_mod.judge(cfg, units, passages)
    return [{"level": [2], "kind": "statement", "text": units[v["unit"]].raw, "reason": v["reason"]} for v in verdict.unsupported], verdict


def merge(l1: list[dict], l2: list[dict]) -> list[dict]:
    """A statement rejected by level 2 that holds a value already flagged by level 1 is one problem
    found by both: the value issue becomes level [1, 2] and the statement is not repeated."""
    out = [dict(i) for i in l1]
    for s in l2:
        same = [i for i in out if i["kind"] == "value" and i["text"] and i["text"] in units_mod.plain(s["text"]) + s["text"]]
        if same:
            for i in same:
                i["level"] = [1, 2]
        else:
            out.append(s)
    return out


def public(check: dict | None, created_at=None) -> dict | None:
    """What the browser gets: never the hidden answer; a check left pending too long is unavailable."""
    if not check:
        return None
    out = {k: v for k, v in check.items() if k != "hidden_answer"}
    if out.get("level2") == "pending" and created_at is not None:
        from app.models.base import utcnow

        created = created_at if created_at.tzinfo else created_at.replace(tzinfo=utcnow().tzinfo)
        if (utcnow() - created).total_seconds() > PENDING_TIMEOUT_S:
            out["level2"] = "unavailable"
    return out


def history_note(check: dict | None) -> str:
    """Added to a flagged answer when it goes back to the LLM as history, so the error does not spread."""
    issues = (check or {}).get("issues") or []
    if not issues or (check or {}).get("hidden"):  # a hidden answer is already replaced by a plain note
        return ""
    parts = [i["text"] for i in issues if i.get("text")][:5]
    what = "; ".join(f'"{p[:120]}"' for p in parts) or "statements without a source"
    return (f"\n\n[Automatic check: this answer contained content not found in the sources ({what}). "
            "Do not rely on it; answer only from the passages.]")
