"""Regression tests for the answer-check review of 0.6.2 (docs/security/review-v0.6.2.md, C-1..C-10):
everything the analyst sees is checked, verdicts are read in any form, values of SOC work are compared."""

import pytest

from app.services import llm
from app.services.answer_check import judge, level1, merge, units, values

P = {1: "Brute force: call Mario Rossi, +39 085 111 2233. Backup: Laura Bianchi. Do not isolate domain controllers. "
        "Command: Invoke-Isolation -Host WS01 -Force. Service account svcbackup. Toll-free 800 123 456.",
     2: "Night shift: call 085 777 8899. Respond within 1 hour 30 minutes, 2-4 hours for low severity."}


def _sent(answer: str) -> list[str]:
    us = units.split(answer)
    return [f"{judge._label(u)}{judge._statement(u)}" for _, u in [(i, u) for i, u in enumerate(us) if judge._nums(u, us)]]


@pytest.mark.parametrize("answer,needle", [
    ("Isolate the host [1]:\n```\nInvoke-Isolation -Host DC01 -Force\n```", "(code block) Invoke-Isolation -Host DC01"),
    ("Escalate to Mario Rossi [1].\n~~~\nCall Anna Verdi on +39 333 0000000 [1].\n~~~", "Call Anna Verdi on +39 333 0000000"),
    ("Escalate [1].\n```\nls\n```bash\nThen call +39 333 0000000 [1].", "Then call +39 333 0000000"),
    ("| Role | Contact |\n|---|---|\n| Primary | Laura Bianchi [1] |", "(table row) Role: Primary | Contact: Laura Bianchi"),
    ("## Call +39 333 9999888 first\n- Call Mario Rossi [1].", "(introduces the next lines) Call +39 333 9999888 first"),
    ("Escalate to Mario Rossi [1].\nWipe the domain controllers.", "(no citation) Wipe the domain controllers"),
    ("Call Mario Rossi [1]. Then wipe DC01.", "(no citation) Then wipe DC01"),
    ("Escalate [1].\n**Never call Laura Bianchi**", "Never call Laura Bianchi"),
    ("Escalate [1].\n| Isolate every domain controller now [1]", "| Isolate every domain controller now"),
    ("Disable the account svc_backup [1].", "Disable the account svc_backup"),
])
def test_every_line_shown_reaches_the_checker(answer, needle):
    assert any(needle in s for s in _sent(answer)), _sent(answer)


def test_code_and_rows_are_checked_at_level_1():
    issues = level1("Isolate [1]:\n```\nping 198.51.100.7\n```\n\n| Night | 085 777 8800 |\n|---|---|", [{"n": 1}], P)
    assert {i["text"] for i in issues} == {"198.51.100.7", "085 777 8800"}


@pytest.mark.parametrize("reply,flagged", [
    ('{"unsupported": [{"statement": 2, "reason": "x"}]}', {1}),
    ('{"unsupported": [{"s": [1, 3]}]}', {0, 2}),
    ('{"unsupported": [{"s": "S1-S3"}]}', {0, 1, 2}),
    ('{"unsupported": [3]}', {2}),
])
def test_verdicts_in_any_form(monkeypatch, reply, flagged):
    monkeypatch.setattr(llm, "call_provider", lambda *a, **k: llm.LLMReply(text=reply))
    us = units.split("Call Mario Rossi [1].\nBlock evil-updates.com [1].\nIsolate the domain controllers [1].")
    v = judge.judge({"name": "C", "model": "m"}, us, P)
    assert {x["unit"] for x in v.unsupported} == flagged and v.checked == 3


def test_unreadable_verdict_is_not_supported(monkeypatch):
    monkeypatch.setattr(llm, "call_provider", lambda *a, **k: llm.LLMReply(text='{"unsupported": [{"why": "wrong"}]}'))
    with pytest.raises(llm.LLMError):
        judge.judge({"name": "C", "model": "m"}, units.split("Call Mario Rossi [1]."), P)


def test_nothing_checked_is_not_matching():
    assert judge.judge({"name": "C", "model": "m"}, units.split("Escalate now."), P).checked == 0


def test_merge_joins_only_the_same_statement():
    l1 = [{"level": [1], "kind": "value", "text": "5 minutes", "statement": "Notify within 5 minutes"}]
    l2 = [{"level": [2], "kind": "statement", "text": "Isolate within 15 minutes", "statement": "Isolate within 15 minutes"}]
    assert [i["level"] for i in merge(l1, l2)] == [[1], [2]]


@pytest.mark.parametrize("answer,wrong", [
    ("Call the toll-free line 800 123 457 [1].", "800 123 457"),
    ("At night call +44 085 777 8899 [2].", "+44 085 777 8899"),
    ("Block 203[.]0[.]113[.]99 [1].", "203.0.113.99"),
    ("Hash 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a0 [1].", "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a0"),
    ("Look for Event ID 4625 [1].", "Event ID 4625"),
    ("After 5 failed logins [1].", "5"),
    ("MAC 00-1A-2B-3C-4D-5E [1].", "00-1A-2B-3C-4D-5E"),
    ("Block evil-updates.com [1].", "evil-updates.com"),
    ("Delete C:\\Windows\\Temp\\x.exe [1].", "C:\\Windows\\Temp\\x.exe"),
    ("Respond within 2h30 [2].", "2h30"),
    ("Respond within fifteen minutes [2].", "fifteen minutes"),
    ("Low severity: 1-4 hours [2].", "1-4 hours"),
    ("Call at 8 PM [2].", "8 PM"),
])
def test_soc_values_are_compared(answer, wrong):
    issues = values.check(units.plain(answer), P, list(P.values()))
    assert [i["text"] for i in issues] == [wrong]


@pytest.mark.parametrize("answer", [
    "Respond within 90 minutes [2].", "Respond within 1.5 hours [2].", "Low severity: up to 4 hours [2].",
    "Call +39 085 **111 2233** [1].", "Toll-free 800 123 456 [1].",
])
def test_same_values_in_other_words_match(answer):
    assert values.check(units.plain(answer), P, list(P.values())) == []


# --- Second round (re-test of the rewritten check) -----------------------------------------------

@pytest.mark.parametrize("answer,needle", [
    ("Do not\nisolate workstations within 15 minutes [1].", "Do not isolate workstations within 15 minutes"),
    ("> Do not\n> isolate workstations [1].", "Do not isolate workstations"),
    ("**Never**\nisolate workstations [1].", "Never isolate workstations"),
    ("Failed logins before the alert [1]:\n- 3", "3"),
    ("| Count [1] |\n|---|\n| 3 |", "Count: 3"),
    ("Disable the account _svcbackup_ [1].", "_svcbackup_"),
])
def test_statements_are_what_the_chat_shows(answer, needle):
    assert any(s.endswith(needle) or needle in s for s in _sent(answer)), _sent(answer)


def test_an_introduction_is_never_the_last_of_a_checker_call():
    us = units.split("\n".join(f"- Step {k}: call Mario Rossi [1]." for k in range(9)) + "\n\n| Backup | Primary |\n|---|---|\n| Mario Rossi [1] | Laura Bianchi [1] |")
    groups = judge._groups([(i, u) for i, u in enumerate(us)])
    assert all(not g[-1][1].intro for g in groups[:-1])
    assert any("Backup: Mario Rossi | Primary: Laura Bianchi" in u.plain for u in us)


def test_invisible_format_characters_are_removed_from_the_answer():
    from app.services.answer import clean_text

    assert clean_text("Call +39 085 111 ‮2233‬ [1] ⁦x⁩") == "Call +39 085 111 2233 [1] x"


def test_hide_mode_treats_unchecked_statements_as_a_failure():
    from app.services.answer_check.runner import _problem, _too_long

    issues = _too_long(judge.Verdict([], unchecked=1))
    assert issues and "more briefly" in _problem(issues[0])


@pytest.mark.parametrize("answer", [
    "Escalate after 1½ hours [2].", "Alert on 4625 [1].", "Opens at 21h [2].", "Window 9-11 PM [2].",
])
def test_more_forms_of_the_same_value_match(answer):
    p = {1: "Event ID 4625.", 2: "Escalate after 1 hour 30 minutes. Opens 21:00. Window 21:00-23:00."}
    assert values.check(units.plain(answer), p, list(p.values())) == []
