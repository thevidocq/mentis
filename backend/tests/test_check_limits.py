"""Answer check level 2: token limit, groups of statements, one more try, stop reasons in errors."""

import json

import pytest

from app.services import llm
from app.services.answer_check import judge, units
from app.services.llm import adapters
from app.services.llm.base import LLMReply

PASSAGES = {1: "Isolate the host. Notify the SOC lead. Export 72 hours of logs within 30 minutes."}


def _units(n):
    return units.split("\n".join(f"- Step number {k} of the procedure to follow [1]." for k in range(n)))


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def fake(cfg, system, turns, timeout=0):
        seen.append({"cfg": cfg, "user": turns[0].content})
        reply = seen_replies.pop(0) if seen_replies else LLMReply('{"unsupported": []}', 10, 5, "end_turn")
        if isinstance(reply, Exception):
            raise reply
        return reply

    seen_replies: list = []
    monkeypatch.setattr(llm, "call_provider", fake)
    return seen, seen_replies


CFG = {"name": "Haiku", "kind": "anthropic", "model": "claude-haiku", "options": {}}


def test_default_limit_and_customer_limit(calls):
    seen, _ = calls
    judge.judge(CFG, _units(3), PASSAGES)
    assert seen[-1]["cfg"]["options"]["max_tokens"] == judge.DEFAULT_MAX_TOKENS == 2500
    judge.judge({**CFG, "check_max_tokens": 6000}, _units(3), PASSAGES)
    assert seen[-1]["cfg"]["options"]["max_tokens"] == 6000


def test_long_answers_are_checked_in_groups(calls):
    seen, replies = calls
    replies += [LLMReply(json.dumps({"unsupported": [{"s": 2, "reason": "x"}]}), 10, 5, "end_turn"),
                LLMReply(json.dumps({"unsupported": [{"s": 3, "reason": "y"}]}), 10, 5, "end_turn")]
    us = _units(14)
    verdict = judge.judge(CFG, us, PASSAGES)
    assert len(seen) == 2 and seen[0]["user"].count("\nS") >= 9 and "S11" not in seen[0]["user"]
    assert [v["unit"] for v in verdict.unsupported] == [1, 12]   # statement 3 of the second group = unit 12


def test_one_more_try_after_an_empty_reply(calls):
    seen, replies = calls
    replies.append(llm.LLMError("Haiku returned an empty answer (stop: refusal)"))
    assert judge.judge(CFG, _units(2), PASSAGES).unsupported == [] and len(seen) == 2


def test_unreadable_twice_says_why(calls):
    _, replies = calls
    replies += [LLMReply('{"unsupported": [', 10, 2500, "max_tokens")] * 2
    with pytest.raises(llm.LLMError, match="raise Max check tokens"):
        judge.judge(CFG, _units(2), PASSAGES)


def test_stop_reasons_are_read():
    assert adapters.parse("anthropic", {"content": [{"type": "text", "text": "ok"}], "stop_reason": "max_tokens"}).stop == "max_tokens"
    assert adapters.parse("openai_chat", {"choices": [{"message": {"content": "ok"}, "finish_reason": "length"}]}).stop == "length"
    r = adapters.parse("openai_responses", {"output_text": "ok", "status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}})
    assert r.stop == "max_output_tokens" and r.stop in adapters.CUT
