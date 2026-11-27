"""Answer check: level 1 (values, no model) and level 2 (a model checks each statement)."""

import json

import pytest
from app.services import answer_check
from app.services.answer_check import merge, units, values

from tests.test_chat import _analyst, _provider, _setup
from tests.test_chat import fake_llm as _fake_llm

fake_llm = _fake_llm

SRC = ("Brute force attacks: call the SOC on-call Mario Rossi, phone +39 085 111 2233. If he does not answer within "
       "15 minutes, call Laura Bianchi, phone +39 085 444 5566. Critical incidents within 30 minutes; high within 2 hours. "
       "Mail soc@acme.example, ticket INC-123456, window 10:30, 99.9% uptime.")


# --- Level 1, pure --------------------------------------------------------------------

@pytest.mark.parametrize("answer", [
    "Chiama **Mario Rossi**, +39 085 1112233 [1], poi Laura entro **15 minuti** [1].",
    "Call 085 111 2233 [1]. High severity within 120 min [1]; critical within 0.5 ore [1].",
    "Write to SOC@ACME.EXAMPLE about INC-123456 at 10:30 [1]; uptime 99,9 % [1].",
])
def test_values_that_match_in_any_wording(answer):
    assert values.check(answer, {1: SRC}, [SRC]) == []


def test_values_that_do_not_match():
    issues = values.check("Critici entro **60 minuti** [1]. Backup: +39 085 444 5656 [1]. Ticket INC-999999 [1].", {1: SRC}, [SRC])
    by_text = {i["text"]: i for i in issues}
    assert set(by_text) == {"60 minuti", "+39 085 444 5656", "INC-999999"}
    assert "expected" not in by_text["60 minuti"]                          # 15 or 30 minutes: ambiguous
    assert by_text["+39 085 444 5656"]["expected"] == "+39 085 444 5566"  # clearly the closest
    assert all(i["level"] == [1] and i["kind"] == "value" for i in issues)


def test_units_and_merge():
    us = units.split("Per **Acme**:\n\n1. Chiama Mario, +39 085 444 5656 [1].\n2. Poi Laura [1]. Apri un ticket [2].")
    assert [(u.plain, u.cites) for u in us] == [("Per Acme", []), ("Chiama Mario, +39 085 444 5656", [1]),
                                               ("Poi Laura", [1]), ("Apri un ticket", [2])]
    l1 = [{"level": [1], "kind": "value", "text": "+39 085 444 5656"}]
    l2 = [{"level": [2], "kind": "statement", "text": us[1].raw}, {"level": [2], "kind": "statement", "text": us[3].raw}]
    merged = merge(l1, l2)
    assert merged[0]["level"] == [1, 2] and [m["text"] for m in merged[1:]] == ["Apri un ticket"]


def test_list_items_take_the_citation_of_their_heading():
    text = ("1. **Triage (rule 'Apache 2.4.49 flaw CVE-2021-41773')**\n"
            "   1. Check source IP, target, HTTP method and timestamp in CommonSecurityLog [1].\n"
            "2. **If it is a true positive** [2]\n"
            "   - Immediately: isolate the entity, block the anomalous access, revoke tokens and sessions.\n"
            "   - Within 30 minutes: export 72 hours of CommonSecurityLog before the alert.\n")
    us = units.split(text)
    by = {u.plain[:20]: u for u in us}
    assert by["Triage (rule 'Apache"].intro and not by["Triage (rule 'Apache"].cites
    assert by["Immediately: isolate"].cites == [2] and by["Immediately: isolate"].inherited
    assert by["Within 30 minutes: e"].cites == [2]
    assert answer_check.level1(text, [{"n": 1}, {"n": 2}], {1: "x", 2: "Isolate the entity; within 30 minutes export 72 hours of logs"}) == []


def test_sentences_on_the_same_line_do_not_inherit():
    us = units.split("Escalate to Mario Rossi [1]. Then isolate the host immediately and reset every password.")
    assert [u.cites for u in us] == [[1], []]


def test_cut_answer_is_recognised():
    from app.services.answer import _parse_json
    data = _parse_json('{"answer": "Step one [1]. Step two and then ve')
    assert data == {"answer": "Step one [1]. Step two and then ve", "_cut": True}
    assert "_cut" not in _parse_json('{"answer": "ok [1]", "not_found": false}')


# --- In the chat -----------------------------------------------------------------------

def _answer(text, cite=True):
    return json.dumps({"answer": text, "not_found": False, "followups": [], "title": "T"})


def _ask(an, tenant_id, q="Who handles brute force escalation?"):
    r = an.post("/api/chats", json={"tenant_id": tenant_id, "message": q})
    assert r.status_code == 201, r.text
    chat = an.get(f"/api/chats/{r.json()['chat']['id']}").json()  # after the background check
    return r.json(), chat["messages"][-1]


def _mode(sa, tenant_id, mode, checker=None):
    r = sa.put(f"/api/tenants/{tenant_id}/llm", json={"answer_check": mode, "checker_id": checker})
    assert r.status_code == 200, r.text


def test_warn_mode_shows_the_answer_then_adds_the_check(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    ex, msg = _ask(an, alfa["id"])
    assert ex["answer"]["check"]["level2"] == "pending" and ex["answer"]["check"]["issues"] == []
    assert msg["check"]["level2"] == "ok" and msg["check"]["issues"] == []
    assert msg["check"]["checker"] == {"name": "Claude", "model": "claude-haiku-5-5"}  # no checker: the answering model
    req = fake_llm.check_requests[-1]["body"]
    assert "MENTIS ANSWER CHECK" in req["system"] and "Mario Rossi" in req["messages"][0]["content"]

    # A statement the checker rejects is flagged by level 2, with the statement to highlight.
    fake_llm.unsupported = [1]
    _, msg = _ask(an, alfa["id"])
    assert [(i["level"], i["kind"]) for i in msg["check"]["issues"]] == [([2], "statement")]
    assert msg["check"]["issues"][0]["text"] in msg["content"]


def test_wrong_value_found_by_both_levels_and_no_citations(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    fake_llm.reply_override = _answer("Call **Mario Rossi**, +39 085 999 0000 [1].")
    _, msg = _ask(an, alfa["id"])
    assert [(i["level"], i["text"]) for i in msg["check"]["issues"]] == [([1], "+39 085 999 0000")]
    fake_llm.unsupported = [1]
    _, msg = _ask(an, alfa["id"])
    assert [(i["level"], i["text"]) for i in msg["check"]["issues"]] == [([1, 2], "+39 085 999 0000")]
    fake_llm.unsupported = []
    fake_llm.reply_override = _answer("Escalate to Mario Rossi.")
    _, msg = _ask(an, alfa["id"])
    assert [i["kind"] for i in msg["check"]["issues"]] == ["no_citations"]


def test_hide_mode_rewrites_once_then_hides(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    _mode(super_admin, alfa["id"], "hide")
    fake_llm.reply_override = _answer("Call **Mario Rossi**, +39 085 999 0000 [1].")
    ex, msg = _ask(an, alfa["id"])
    assert ex["answer"]["status"] == "not_found" and "did not match the sources" in ex["answer"]["content"]
    assert msg["check"]["hidden"] is True and "hidden_answer" not in msg["check"] and "999" not in json.dumps(msg)
    # The second attempt was told what was wrong.
    assert "previous draft of this answer was rejected" in fake_llm.requests[-1]["body"]["messages"][-1]["content"]
    # A correct answer passes at once.
    fake_llm.reply_override = None
    ex, msg = _ask(an, alfa["id"])
    assert ex["answer"]["status"] == "ok" and ex["answer"]["check"]["level2"] == "ok"


def test_off_mode_and_unavailable_checker(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    _mode(super_admin, alfa["id"], "off")
    n = len(fake_llm.check_requests)
    _, msg = _ask(an, alfa["id"])
    assert msg["check"]["level2"] == "off" and len(fake_llm.check_requests) == n
    # A checker that cannot answer: the answer stays, the check says it is not available.
    checker = super_admin.post("/api/llm/providers", json={"name": "Checker", "kind": "openai_chat", "base_url": "http://down.example/v1",
                                                           "model": "small", "role": "checker"}).json()
    _mode(super_admin, alfa["id"], "warn", checker["id"])
    fake_llm.fail["down.example"] = 500
    ex, msg = _ask(an, alfa["id"])
    assert ex["answer"]["status"] == "ok" and msg["check"]["level2"] == "unavailable"


def test_which_model_checks(super_admin, fake_llm):
    _provider(super_admin)
    alfa, beta = _setup(super_admin)
    an = _analyst(super_admin)
    c1 = super_admin.post("/api/llm/providers", json={"name": "Checker A", "kind": "openai_chat", "base_url": "http://checker-a/v1",
                                                      "model": "small", "role": "checker"}).json()
    c2 = super_admin.post("/api/llm/providers", json={"name": "Checker B", "kind": "openai_chat", "base_url": "http://checker-b/v1",
                                                      "model": "small", "role": "checker"}).json()
    assert c1["is_default"] and not c2["is_default"]  # adding a second model never changes the default
    _ask(an, alfa["id"])
    assert "checker-a" in fake_llm.check_requests[-1]["url"]
    assert super_admin.post(f"/api/llm/providers/{c2['id']}/default").json()["is_default"]
    _ask(an, alfa["id"])
    assert "checker-b" in fake_llm.check_requests[-1]["url"]
    # A customer with its own LLM: its data stays with that provider.
    own = _provider(super_admin, name="Own", base_url="http://own-llm/v1", kind="openai_chat")
    assert super_admin.put(f"/api/tenants/{alfa['id']}/llm", json={"provider_id": own["id"]}).status_code == 200
    _ask(an, alfa["id"])
    assert "own-llm" in fake_llm.check_requests[-1]["url"]
    # ... unless a checker is chosen for it. Roles are kept apart.
    assert super_admin.put(f"/api/tenants/{alfa['id']}/llm", json={"provider_id": own["id"], "checker_id": c1["id"]}).status_code == 200
    _ask(an, alfa["id"])
    assert "checker-a" in fake_llm.check_requests[-1]["url"]
    assert super_admin.put(f"/api/tenants/{alfa['id']}/llm", json={"checker_id": own["id"]}).status_code == 422
    assert super_admin.put(f"/api/tenants/{alfa['id']}/llm", json={"provider_id": c1["id"]}).status_code == 422
    assert super_admin.delete(f"/api/llm/providers/{c1['id']}").status_code == 409  # in use by Alfa
    # Usage rows for the checks.
    rows = {r["provider"] for r in super_admin.get("/api/usage", params={"days": 1}).json()["rows"]}
    assert {"Checker A · answer check", "Checker B · answer check", "Own · answer check"} <= rows


def test_sentence_checker_format(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    super_admin.post("/api/llm/providers", json={"name": "MiniCheck", "kind": "openai_chat", "base_url": "http://ollama:11434/v1",
                                                  "model": "bespoke-minicheck", "role": "checker"})
    fake_llm.minicheck_no = ["Mario Rossi"]
    _, msg = _ask(an, alfa["id"])
    assert fake_llm.check_requests[-1]["body"]["messages"][-1]["content"].startswith("Document: ")
    assert [i["level"] for i in msg["check"]["issues"]] == [[2]]


def test_flagged_answer_goes_back_with_a_note(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    fake_llm.reply_override = _answer("Call **Mario Rossi**, +39 085 999 0000 [1].")
    ex, _ = _ask(an, alfa["id"])
    fake_llm.reply_override = None
    an.post(f"/api/chats/{ex['chat']['id']}/messages", json={"message": "and the backup contact?"})
    history = fake_llm.requests[-1]["body"]["messages"]
    assert "Automatic check" in history[1]["content"] and "+39 085 999 0000" in history[1]["content"]
    # The shared chat shows the same check.
    tok = an.post(f"/api/chats/{ex['chat']['id']}/share").json()["url"].rsplit("/", 1)[1]
    shared = an.get(f"/api/shared/{tok}").json()
    assert shared["messages"][1]["check"]["issues"][0]["text"] == "+39 085 999 0000"


def test_temperature_and_checker_test_button(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    _ask(an, alfa["id"])
    assert fake_llm.requests[-1]["body"]["temperature"] == 0 and fake_llm.check_requests[-1]["body"]["temperature"] == 0
    c = super_admin.post("/api/llm/providers", json={"name": "Checker", "kind": "anthropic", "base_url": "https://api.anthropic.com",
                                                     "model": "claude-haiku-5-5", "api_key": "k", "role": "checker"}).json()
    r = super_admin.post(f"/api/llm/providers/{c['id']}/test").json()
    assert r["ok"] is False and "did not catch" in r["error"]
    fake_llm.unsupported = [2]
    assert super_admin.post(f"/api/llm/providers/{c['id']}/test").json()["ok"] is True


def test_models_that_refuse_temperature_are_asked_again_without_it():
    import httpx
    from app.services import llm

    bodies = []

    def handle(request):
        body = json.loads(request.content)
        bodies.append(body)
        if "temperature" in body:
            return httpx.Response(400, json={"error": {"message": "Unsupported value: 'temperature' does not support 0"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    llm.set_transport(httpx.MockTransport(handle))
    try:
        cfg = {"name": "o", "kind": "openai_chat", "base_url": "https://api.openai.com/v1", "model": "o-model", "api_key": "k", "options": {}}
        assert llm.call_provider(cfg, "s", [llm.Turn("user", "q")]).text == "ok"
        assert "temperature" in bodies[0] and "temperature" not in bodies[1]
    finally:
        llm.set_transport(None)


# --- Robustness ------------------------------------------------------------------------

@pytest.mark.parametrize("text", ["Logs from 2023-2024 [1].", "Since 2024-05-12 [1].", "About 1.000.000 events [1].",
                                  "Between 1000 - 2000 events [1].", "Keep 10,000,000 rows [1]."])
def test_numbers_that_are_not_phone_numbers(text):
    assert [v for v in values.extract(text) if v.kind == "phone"] == []


def test_hidden_answer_goes_back_without_a_note():
    from app.services.answer_check import history_note
    assert history_note({"issues": [{"level": [1], "kind": "value"}], "hidden": True}) == ""


def test_hide_mode_when_the_rewrite_fails(super_admin, fake_llm, monkeypatch):
    from app.api.routes import chats as chat_routes
    from app.services.llm import LLMError
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    _mode(super_admin, alfa["id"], "hide")
    real = chat_routes.answering.answer

    def answer(*a, correction=None, **kw):
        if correction:
            raise LLMError("provider down")
        return real(*a, **kw)
    monkeypatch.setattr(chat_routes.answering, "answer", answer)
    fake_llm.reply_override = _answer("Call **Mario Rossi**, +39 085 999 0000 [1].")
    ex, msg = _ask(an, alfa["id"])
    assert ex["answer"]["status"] == "not_found" and msg["check"]["hidden"] is True and "999" not in json.dumps(msg)


def test_a_broken_check_never_breaks_the_chat(super_admin, fake_llm, monkeypatch):
    from app.services import answer_check
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)

    def boom(*a, **kw):
        raise ValueError("bug")
    monkeypatch.setattr(answer_check, "level2", boom)
    monkeypatch.setattr(answer_check, "level1", boom)
    ex, msg = _ask(an, alfa["id"])
    assert ex["answer"]["status"] == "ok" and msg["check"]["level2"] == "unavailable"
    _mode(super_admin, alfa["id"], "hide")
    ex, msg = _ask(an, alfa["id"])
    assert ex["answer"]["status"] == "ok" and msg["check"]["level2"] == "unavailable"


def test_a_crash_around_the_check_keeps_the_answer(super_admin, fake_llm, monkeypatch):
    from app.api.routes import chats as chat_routes

    def boom(*a, **kw):
        raise ValueError("bug")
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    monkeypatch.setattr(chat_routes.check_runner, "before_save", boom)
    ex, msg = _ask(an, alfa["id"])
    assert ex["answer"]["status"] == "ok" and msg["check"]["level2"] == "unavailable"
