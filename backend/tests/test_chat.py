import pytest

from app.services import llm
from tests.conftest import approve_general, login, new_client, run_jobs
from tests.fake_llm import FakeLLM
from tests.test_indexing import _docx, _general, _tenant, _upload
from tests.test_tenants_users import _invite_and_accept


@pytest.fixture
def fake_llm():
    f = FakeLLM()
    llm.set_transport(f.transport())
    yield f
    llm.set_transport(None)


def _provider(c, name="Claude", kind="anthropic", base_url="https://api.anthropic.com", model="claude-haiku-5-5", **kw):
    r = c.post("/api/llm/providers", json={"name": name, "kind": kind, "base_url": base_url, "model": model, "api_key": "sk-test", **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _setup(c):
    """Two customers with different escalation contacts, plus a General runbook."""
    alfa, beta = _tenant(c, "Alfa"), _tenant(c, "Beta")
    _upload(c, alfa["id"], "Escalation.docx", _docx("Escalate brute force attacks to Mario Rossi phone 111"))
    _upload(c, beta["id"], "Escalation.docx", _docx("Escalate brute force attacks to Anna Verdi phone 222"))
    _upload(c, _general(c)["id"], "Runbook.docx", _docx("Phishing triage checklist: check headers and sender reputation"))
    approve_general(c)
    return alfa, beta


def _analyst(c):
    _invite_and_accept(c, "an@example.com", "analyst")
    an = new_client(c.app)
    login(an, "an@example.com")
    return an


# --- Adapters --------------------------------------------------------------------

@pytest.mark.parametrize("kind,base,path", [
    ("anthropic", "https://api.anthropic.com", "/v1/messages"),
    ("openai_chat", "https://api.openai.com/v1", "/v1/chat/completions"),
    ("openai_responses", "http://vllm:8000/v1", "/v1/responses"),
])
def test_adapters_request_and_parse(fake_llm, kind, base, path):
    fake_llm.reply_override = "ready"
    cfg = {"name": "x", "kind": kind, "base_url": base, "model": "m", "api_key": "k", "options": {"reasoning_effort": "low"}}
    reply = llm.call_provider(cfg, "sys", [llm.Turn("user", "hi")])
    assert reply.text == "ready" and reply.input_tokens == 100 and reply.output_tokens == 20
    req = fake_llm.requests[-1]
    assert req["url"].endswith(path)
    b = req["body"]
    if kind == "anthropic":
        assert req["headers"]["x-api-key"] == "k" and b["system"] == "sys" and b["messages"] == [{"role": "user", "content": "hi"}]
    elif kind == "openai_chat":
        assert req["headers"]["authorization"] == "Bearer k" and b["messages"][0] == {"role": "system", "content": "sys"}
        assert "max_completion_tokens" in b
    else:
        assert b["instructions"] == "sys" and b["reasoning"] == {"effort": "low"} and "max_output_tokens" in b


def test_failover_and_errors(fake_llm):
    a = {"name": "A", "kind": "anthropic", "base_url": "https://down.example", "model": "m", "api_key": "k", "options": {}}
    b = {"name": "B", "kind": "openai_chat", "base_url": "http://ollama:11434/v1", "model": "m", "api_key": None, "options": {}}
    fake_llm.reply_override = "ok"
    fake_llm.fail["down.example"] = 500
    reply, used, _ = llm.call_with_failover(a, b, "s", [llm.Turn("user", "q")])
    assert used["name"] == "B" and reply.text == "ok"
    fake_llm.fail["ollama"] = 401
    with pytest.raises(llm.LLMError) as e:
        llm.call_with_failover(a, b, "s", [llm.Turn("user", "q")])
    assert "A" in str(e.value) and "B" in str(e.value)
    with pytest.raises(llm.LLMError, match="No LLM is configured"):
        llm.call_with_failover(None, None, "s", [])


# --- Providers API -----------------------------------------------------------------

def test_providers_api(super_admin, fake_llm):
    p1 = _provider(super_admin)
    assert p1["is_default"] and p1["api_key_set"] and "api_key" not in p1
    p2 = _provider(super_admin, name="Ollama", kind="openai_chat", base_url="http://ollama:11434/v1", model="llama3.1")
    assert not p2["is_default"]
    assert super_admin.post("/api/llm/providers", json={**p1, "kind": "nope", "name": "X"}).status_code == 422
    assert super_admin.post(f"/api/llm/providers/{p1['id']}/test").json()["ok"] is True
    # Tenant choice, then deleting a provider in use is refused.
    alfa = _tenant(super_admin, "Alfa")
    r = super_admin.put(f"/api/tenants/{alfa['id']}/llm", json={"provider_id": p2["id"], "fallback_id": p1["id"]})
    assert r.status_code == 200, r.text
    assert super_admin.delete(f"/api/llm/providers/{p2['id']}").status_code == 409


def test_provider_management_is_super_admin_only(super_admin):
    alfa = _tenant(super_admin, "Alfa")
    an = _analyst(super_admin)
    assert an.get("/api/llm/providers").status_code == 403
    assert an.post("/api/llm/providers", json={"name": "x", "kind": "anthropic", "base_url": "https://a.b", "model": "m"}).status_code == 403
    _invite_and_accept(super_admin, "ta@example.com", "tenant_admin", alfa["id"])
    ta = new_client(super_admin.app)
    login(ta, "ta@example.com")
    assert ta.get("/api/llm/providers").status_code == 200
    assert ta.post("/api/llm/providers", json={"name": "x", "kind": "anthropic", "base_url": "https://a.b", "model": "m"}).status_code == 403
    beta = _tenant(super_admin, "Beta")
    assert ta.put(f"/api/tenants/{beta['id']}/llm", json={}).status_code == 404
    assert ta.put(f"/api/tenants/{alfa['id']}/llm", json={}).status_code == 200


# --- Chat ----------------------------------------------------------------------------

def test_chat_answers_from_scoped_customer_with_citations(super_admin, fake_llm):
    _provider(super_admin)
    alfa, beta = _setup(super_admin)
    an = _analyst(super_admin)
    r = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "Who handles brute force escalation?"})
    assert r.status_code == 201, r.text
    ex = r.json()
    a = ex["answer"]
    assert a["status"] == "ok" and "Mario Rossi" in a["content"]
    assert "Anna Verdi" not in a["content"]
    # [9] does not exist and is dropped; [1] becomes a citation with document, version and page.
    assert "[9]" not in a["content"] and [c["n"] for c in a["citations"]] == [1]
    c = a["citations"][0]
    assert c["tenant"] == "Alfa" and c["document"] == "Escalation.docx" and c["version"] == 1 and c["page"]
    assert a["tenants"] == ["Alfa"] and a["followups"] and a["provider_name"] == "Claude"
    assert ex["chat"]["title"] == "Escalation procedure" and ex["chat"]["scope_name"] == "Alfa"
    # The LLM only saw Alfa (+ General), never Beta.
    sent = fake_llm.requests[-1]["body"]["messages"][-1]["content"]
    assert "Anna Verdi" not in sent and 'customer="Alfa"' in sent


def test_scope_is_locked_to_the_chat(super_admin, fake_llm):
    _provider(super_admin)
    alfa, beta = _setup(super_admin)
    an = _analyst(super_admin)
    chat = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"}).json()["chat"]
    # A tenant_id in a follow-up message is ignored: the chat's scope is used.
    r = an.post(f"/api/chats/{chat['id']}/messages", json={"message": "brute force escalation contact", "tenant_id": beta["id"]})
    assert r.status_code == 200, r.text
    assert "Mario Rossi" in r.json()["answer"]["content"]
    assert r.json()["chat"]["title"] == "Escalation procedure"  # title set once, from the first exchange
    full = an.get(f"/api/chats/{chat['id']}").json()
    assert [m["role"] for m in full["messages"]] == ["user", "assistant", "user", "assistant"]
    # History is sent to the LLM on follow-ups.
    assert len(fake_llm.requests[-1]["body"]["messages"]) == 3


def test_all_customers_names_each_customer(super_admin, fake_llm):
    _provider(super_admin)
    _setup(super_admin)
    an = _analyst(super_admin)
    ex = an.post("/api/chats", json={"tenant_id": None, "message": "brute force escalation"}).json()
    sent = fake_llm.requests[-1]["body"]["messages"][-1]["content"]
    assert "Mario Rossi" in sent and "Anna Verdi" in sent and "CUSTOMER SCOPE: All customers" in sent
    assert ex["chat"]["scope_name"] == "All customers"


def test_not_found_does_not_call_the_llm(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    ex = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "zzz qqq xyzzy"}).json()
    assert ex["answer"]["status"] == "not_found" and "Not found in the documentation of Alfa" in ex["answer"]["content"]
    assert ex["answer"]["citations"] == [] and fake_llm.requests == []
    assert ex["chat"]["title"] == "zzz qqq xyzzy"


def test_model_not_found_flag_and_plain_text_reply(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    fake_llm.reply_override = '{"answer": "The documents do not say.", "not_found": true, "followups": ["x"], "title": "T"}'
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"}).json()["answer"]
    assert a["status"] == "not_found" and a["citations"] == [] and a["followups"] == []
    # A model that ignores the JSON format still produces an answer.
    fake_llm.reply_override = "Call Mario Rossi [1]."
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"}).json()["answer"]
    assert a["status"] == "ok" and a["content"] == "Call Mario Rossi [1]." and a["citations"][0]["n"] == 1


def test_followups_follow_tenant_setting(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    super_admin.patch(f"/api/tenants/{alfa['id']}", json={"settings": {"suggested_followups": False}})
    an = _analyst(super_admin)
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"}).json()["answer"]
    assert a["status"] == "ok" and a["followups"] == []


def test_llm_error_is_saved_as_error_message(super_admin, fake_llm):
    alfa, _ = _setup(super_admin)  # no provider configured
    an = _analyst(super_admin)
    r = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"})
    assert r.status_code == 201
    a = r.json()["answer"]
    assert a["status"] == "error" and "No LLM is configured" in a["content"]


def test_tenant_llm_choice_and_failover(super_admin, fake_llm):
    _provider(super_admin)
    local = _provider(super_admin, name="gpt-oss", kind="openai_responses", base_url="http://vllm:8000/v1", model="openai/gpt-oss-120b")
    backup = _provider(super_admin, name="Ollama", kind="openai_chat", base_url="http://ollama:11434/v1", model="llama3.1")
    alfa, _ = _setup(super_admin)
    super_admin.put(f"/api/tenants/{alfa['id']}/llm", json={"provider_id": local["id"], "fallback_id": backup["id"]})
    an = _analyst(super_admin)
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"}).json()["answer"]
    assert a["provider_name"] == "gpt-oss" and fake_llm.requests[-1]["url"].endswith("/responses")
    fake_llm.fail["vllm"] = 503
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"}).json()["answer"]
    assert a["status"] == "ok" and a["provider_name"] == "Ollama"


def test_chats_are_private_and_manageable(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    ex = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"}).json()
    cid, mid = ex["chat"]["id"], ex["answer"]["id"]
    # Other users cannot see it.
    assert super_admin.get(f"/api/chats/{cid}").status_code == 404
    assert super_admin.get("/api/chats").json() == []
    # Search, rename (locks the title), feedback, delete.
    assert [c["id"] for c in an.get("/api/chats", params={"q": "brute"}).json()] == [cid]
    assert an.get("/api/chats", params={"q": "nothing-like-this"}).json() == []
    assert an.patch(f"/api/chats/{cid}", json={"title": "My title"}).json()["title"] == "My title"
    an.post(f"/api/chats/{cid}/messages", json={"message": "brute force"})
    assert an.get(f"/api/chats/{cid}").json()["title"] == "My title"
    assert an.post(f"/api/chats/{cid}/messages/{mid}/feedback", json={"value": -1}).json()["feedback"] == -1
    assert an.post(f"/api/chats/{cid}/messages/{mid}/feedback", json={"value": 5}).status_code == 422
    assert super_admin.post(f"/api/chats/{cid}/messages/{mid}/feedback", json={"value": 1}).status_code == 404
    assert an.delete(f"/api/chats/{cid}").status_code == 204
    assert an.get(f"/api/chats/{cid}").status_code == 404


def test_scopes_and_tenant_admin_limits(super_admin, fake_llm):
    _provider(super_admin)
    alfa, beta = _setup(super_admin)
    an = _analyst(super_admin)
    scopes = an.get("/api/chats/scopes").json()
    assert [s["name"] for s in scopes] == ["All customers", "Alfa", "Beta", "General Knowledge Base"] and scopes[-1]["is_general"]
    # General alone: only the shared documentation is searched.
    g = an.post("/api/chats", json={"tenant_id": _general(super_admin)["id"], "message": "brute force escalation"}).json()
    assert g["chat"]["scope_name"] == "General Knowledge Base" and g["answer"]["status"] == "not_found"
    g = an.post("/api/chats", json={"tenant_id": _general(super_admin)["id"], "message": "phishing triage checklist"}).json()
    assert g["answer"]["status"] == "ok" and all(c["is_general"] for c in g["answer"]["citations"])
    _invite_and_accept(super_admin, "ta@example.com", "tenant_admin", alfa["id"])
    ta = new_client(super_admin.app)
    login(ta, "ta@example.com")
    assert [s["name"] for s in ta.get("/api/chats/scopes").json()] == ["Alfa", "General Knowledge Base"]
    assert ta.post("/api/chats", json={"tenant_id": beta["id"], "message": "x"}).status_code == 403
    # "All my customers" for a tenant admin covers only its own tenants.
    own_all = ta.post("/api/chats", json={"tenant_id": None, "message": "brute force escalation"}).json()
    assert own_all["chat"]["scope_name"] == "All my customers" and "Anna Verdi" not in own_all["answer"]["content"]
    assert ta.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"}).status_code == 201


def test_deleting_tenant_removes_its_chats(super_admin, fake_llm):
    _provider(super_admin)
    alfa, beta = _setup(super_admin)
    an = _analyst(super_admin)
    c_alfa = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force"}).json()["chat"]["id"]
    c_beta = an.post("/api/chats", json={"tenant_id": beta["id"], "message": "brute force"}).json()["chat"]["id"]
    r = super_admin.request("DELETE", f"/api/tenants/{alfa['id']}", json={"confirm_name": "Alfa"})
    assert r.status_code == 204, r.text
    assert [c["id"] for c in an.get("/api/chats").json()] == [c_beta]
    assert an.get(f"/api/chats/{c_alfa}").status_code == 404


def test_disabled_customer_blocks_new_messages(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    cid = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force"}).json()["chat"]["id"]
    super_admin.patch(f"/api/tenants/{alfa['id']}", json={"status": "disabled"})
    assert an.post(f"/api/chats/{cid}/messages", json={"message": "again"}).status_code == 409
    assert an.get(f"/api/chats/{cid}").json()["scope_available"] is False
    assert an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "x"}).status_code == 409


def test_status_lists_llm_providers(super_admin, fake_llm):
    names = lambda: {s["name"]: s for s in super_admin.get("/api/platform/status").json()["services"]}  # noqa: E731
    assert names()["AI provider"]["state"] == "down"
    _provider(super_admin)
    _provider(super_admin, name="Ollama", kind="openai_chat", base_url="http://ollama:11434/v1", model="llama3.1")
    fake_llm.fail["ollama"] = 401
    s = names()
    assert s["LLM: Claude (default)"]["state"] == "ok"
    assert s["LLM: Ollama"]["state"] == "down" and "invalid API key" in s["LLM: Ollama"]["detail"]
    assert fake_llm.requests == []  # the check lists models: nothing is generated


def test_tenant_admin_of_several_tenants(super_admin, fake_llm):
    _provider(super_admin)
    alfa, beta = _setup(super_admin)
    gamma = _tenant(super_admin, "Gamma")
    _invite_and_accept(super_admin, "ta@example.com", "tenant_admin", tenant_ids=[alfa["id"], beta["id"]])
    ta = new_client(super_admin.app)
    login(ta, "ta@example.com")
    me = ta.get("/api/auth/me").json()
    # Reads the General Knowledge Base (chat) without managing it.
    assert sorted(t["name"] for t in me["tenants"]) == ["Alfa", "Beta", "General Knowledge Base"] and me["can_manage_general"] is False
    assert sorted(t["name"] for t in ta.get("/api/tenants").json()) == ["Alfa", "Beta"]  # what it administers
    # Documents, settings and LLM of both; not of Gamma.
    for t in (alfa, beta):
        assert ta.get(f"/api/tenants/{t['id']}/documents").status_code == 200
        assert ta.get(f"/api/tenants/{t['id']}/llm").status_code == 200
    assert ta.get(f"/api/tenants/{gamma['id']}/documents").status_code == 404
    assert ta.patch(f"/api/tenants/{gamma['id']}", json={"settings": {"include_general": False}}).status_code in (403, 404)
    # Chat: @ lists its customers plus "All my customers"; that scope searches both, not Gamma.
    assert [s["name"] for s in ta.get("/api/chats/scopes").json()] == ["All my customers", "Alfa", "Beta", "General Knowledge Base"]
    ta.post("/api/chats", json={"tenant_id": None, "message": "brute force escalation"})
    sent = fake_llm.requests[-1]["body"]["messages"][-1]["content"]
    assert "Mario Rossi" in sent and "Anna Verdi" in sent
    assert ta.post("/api/chats", json={"tenant_id": gamma["id"], "message": "x"}).status_code == 403
    # It may invite admins only within its tenants.
    ok = ta.post("/api/invitations", json={"email": "b@example.com", "full_name": "B", "role": "tenant_admin", "tenant_ids": [alfa["id"]]})
    assert ok.status_code == 201
    bad = ta.post("/api/invitations", json={"email": "c@example.com", "full_name": "C", "role": "tenant_admin", "tenant_ids": [alfa["id"], gamma["id"]]})
    assert bad.status_code == 403
    assert [i["email"] for i in ta.get("/api/invitations").json()] == ["b@example.com"]


def test_super_admin_changes_tenants_and_deleting_one_keeps_the_admin(super_admin, fake_llm):
    alfa, beta = _setup(super_admin)
    _invite_and_accept(super_admin, "ta@example.com", "tenant_admin", tenant_ids=[alfa["id"]])
    ta_id = next(u["id"] for u in super_admin.get("/api/users").json() if u["email"] == "ta@example.com")
    r = super_admin.patch(f"/api/users/{ta_id}", json={"tenant_ids": [alfa["id"], beta["id"]]})
    assert r.status_code == 200 and sorted(t["name"] for t in r.json()["tenants"]) == ["Alfa", "Beta"]
    assert super_admin.patch(f"/api/users/{ta_id}", json={"tenant_ids": []}).status_code == 422
    # Analysts keep their customers; super-admins have none.
    assert [t["name"] for t in super_admin.patch(f"/api/users/{ta_id}", json={"role": "analyst"}).json()["tenants"]] == ["Alfa", "Beta"]
    assert super_admin.patch(f"/api/users/{ta_id}", json={"role": "super_admin"}).json()["tenants"] == []
    super_admin.patch(f"/api/users/{ta_id}", json={"role": "tenant_admin", "tenant_ids": [alfa["id"], beta["id"]]})
    # A pending invitation on Alfa and Beta loses Alfa; one only on Alfa disappears.
    super_admin.post("/api/invitations", json={"email": "p1@example.com", "full_name": "P1", "role": "tenant_admin", "tenant_ids": [alfa["id"], beta["id"]]})
    super_admin.post("/api/invitations", json={"email": "p2@example.com", "full_name": "P2", "role": "tenant_admin", "tenant_ids": [alfa["id"]]})
    assert super_admin.request("DELETE", f"/api/tenants/{alfa['id']}", json={"confirm_name": "Alfa"}).status_code == 204
    users = {u["email"]: u for u in super_admin.get("/api/users").json()}
    assert [t["name"] for t in users["ta@example.com"]["tenants"]] == ["Beta"]
    invs = {i["email"]: i for i in super_admin.get("/api/invitations").json()}
    assert "p2@example.com" not in invs and [t["name"] for t in invs["p1@example.com"]["tenants"]] == ["Beta"]
    # Deleting its last tenant deletes the admin.
    super_admin.request("DELETE", f"/api/tenants/{beta['id']}", json={"confirm_name": "Beta"})
    assert "ta@example.com" not in {u["email"] for u in super_admin.get("/api/users").json()}


def test_greeting_gets_a_hint_not_an_llm_call(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    a = super_admin.post("/api/chats", json={"tenant_id": alfa["id"], "message": "Ciao!"}).json()["answer"]
    assert a["status"] == "not_found" and "Alfa's procedures" in a["content"] and fake_llm.requests == []


def test_unexpected_check_error_keeps_the_answer(super_admin, fake_llm, monkeypatch):
    from app.services.answer_check import runner

    def boom(*a, **kw):
        raise RuntimeError("bug")
    monkeypatch.setattr(runner, "before_save", boom)
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    r = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "Who handles brute force escalation?"})
    assert r.status_code == 201, r.text
    assert r.json()["answer"]["status"] == "ok" and r.json()["answer"]["check"]["level2"] == "unavailable"


def test_grouped_citation_markers_become_citations(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    fake_llm.reply_override = '{"answer": "Call Mario Rossi [1, 9] or check headers [1,2].", "not_found": false}'
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"}).json()["answer"]
    assert "[1, 9]" not in a["content"] and "[1,2]" not in a["content"]
    assert [c["n"] for c in a["citations"]][:1] == [1] and "[1]" in a["content"]


def test_customer_name_with_quotes_keeps_the_passage_tag_well_formed():
    from types import SimpleNamespace

    from app.services import prompts
    p = SimpleNamespace(is_general=False, tenant_name='Acme "EU" source="x', document_name="d.docx", version=1,
                        page_label="Page 1", heading=None, text="Call 111")
    tag = prompts.passages_block([p]).splitlines()[1]
    assert tag.count('"') == 8 and "customer=\"Acme 'EU' source='x\"" in tag


def test_string_not_found_and_nul_characters(super_admin, fake_llm):
    _provider(super_admin)
    alfa, _ = _setup(super_admin)
    an = _analyst(super_admin)
    fake_llm.reply_override = '{"answer": "Call Mario Rossi\\u0000 [1].", "not_found": "false", "title": "T\\u0000"}'
    r = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force\x00 escalation"})
    assert r.status_code == 201, r.text
    a = r.json()["answer"]
    assert a["status"] == "ok" and "\x00" not in a["content"] and a["citations"]
