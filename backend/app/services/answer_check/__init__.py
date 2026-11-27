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
Issues: {"level": [1] | [2] | [1, 2], "kind": "value" | "statement" | "uncited" | "no_citations", "text", "expected"?, "reason"?}
"""

from app.services.answer_check import judge as judge_mod
from app.services.answer_check import units as units_mod
from app.services.answer_check import values

MODES = ("warn", "hide", "off")
DEFAULT_MODE = "warn"
PENDING_TIMEOUT_S = 200  # longer than the check itself (judge.TOTAL_SECONDS)


def mode_of(settings: dict | None) -> str:
    m = (settings or {}).get("answer_check")
    return m if m in MODES else DEFAULT_MODE


def _substantive(u: units_mod.Unit) -> bool:
    """A statement that must cite a source: any line with a value (contact, time, code...), or a
    statement of at least six words that is not an introduction ("For Acme:", a list heading)."""
    return bool(values.extract(u.raw)) or (not u.intro and len(u.plain.split()) >= 6)


def level1(content: str, citations: list[dict], passages: dict[int, str]) -> list[dict]:
    """Values and citations, no model.

    - Each statement's values must be in the passages **that statement** cites (a value found only in
      another passage, e.g. an attacker's ticket or another customer's document, does not count).
    - A substantive statement without a citation is an issue ("uncited"): level 2 checks only cited
      statements, so an uncited one would otherwise pass unchecked.
    - An answer with no citation at all is one issue ("no_citations").
    """
    if not citations:
        cited = {}
        issues = values.check(content, cited, list(passages.values()))
        issues.append({"level": [1], "kind": "no_citations", "text": ""})
        return issues
    issues: list[dict] = []
    for u in units_mod.split(content):
        if not u.cites:
            if u.scope and values.extract(u.raw):
                # An uncited heading over cited items: its values must be in the passages its items cite.
                scope = {n: passages[n] for n in u.scope if n in passages}
                issues += values.check(u.raw, scope, list(scope.values()))
            elif _substantive(u):
                issues.append({"level": [1], "kind": "uncited", "text": u.raw})
            continue
        own = {n: passages[n] for n in u.cites if n in passages}
        issues += values.check(u.raw, own, list(own.values()))
    # Table rows are not statements, but their values (a phone, an address) must still come from the
    # passages: the row's own citations, else any passage the answer cites.
    cited_all = {c for u in units_mod.split(content) for c in u.cites} | {c for _, cs in units_mod.table_rows(content) for c in cs}
    for row, cites in units_mod.table_rows(content):
        scope = {n: passages[n] for n in (cites or cited_all) if n in passages}
        issues += values.check(units_mod.plain(row), scope, list(scope.values()))
    out, seen = [], set()
    for i in issues:
        key = (i["kind"], i["text"])
        if key not in seen:
            seen.add(key)
            out.append(i)
    return out


def level2(cfg: dict, content: str, passages: dict[int, str]) -> tuple[list[dict], judge_mod.Verdict]:
    """Statements the checker rejects, as issues (raises llm.LLMError when it cannot check)."""
    units = units_mod.split(content)
    verdict = judge_mod.judge(cfg, units, passages)
    return [{"level": [2], "kind": "statement", "text": units[v["unit"]].raw, "reason": v["reason"]} for v in verdict.unsupported], verdict


def merge(l1: list[dict], l2: list[dict]) -> list[dict]:
    """A statement rejected by level 2 that holds a value already flagged by level 1 is one problem
    found by both: the value issue becomes level [1, 2] and the statement is not repeated."""
    out = [dict(i) for i in l1]
    l2 = list({(s["kind"], s["text"]): s for s in l2}.values())  # the checker may name a statement twice
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
    parts = [i["text"] for i in issues if i.get("text")][:5]  # values, unsupported and uncited statements
    what = "; ".join(f'"{p[:120]}"' for p in parts) or "statements without a source"
    return (f"\n\n[Automatic check: this answer contained content not found in the sources ({what}). "
            "Do not rely on it; answer only from the passages.]")
