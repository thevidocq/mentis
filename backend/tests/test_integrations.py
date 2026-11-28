"""Integrations (#): plugins enabled by the super-admin, instances per customer, live data in answers.

The FakeDesk plugin (tests/fake_connector.py) runs through the real core path: registry, the
read-only HTTP client (with a mock transport) and the chat answer.
"""

import json

import httpx
import pytest
from sqlalchemy import select

from app.connectors import http as connector_http
from app.connectors import registry
from app.connectors.contract import ConnectorError
from app.core import db as db_module
from app.models import AuditEvent, Integration
from app.services import llm
from tests.conftest import login, new_client
from tests.fake_connector import FakeDesk, FakeDeskServer
from tests.fake_llm import FakeLLM
from tests.http_mock import answer
from tests.test_chat import _analyst, _provider, _setup
from tests.test_tenants_users import _invite_and_accept

URL = "https://desk.example.com"
TOKEN = "tok-SECRET-1"


@pytest.fixture
def fake_llm():
    f = FakeLLM()
    llm.set_transport(f.transport())
    yield f
    llm.set_transport(None)


@pytest.fixture
def desk():
    registry.set_connectors({"fakedesk": FakeDesk()})
    server = FakeDeskServer()
    connector_http.set_transport(server.transport())
    connector_http.set_resolver(lambda host: ["93.184.216.34"])  # a public address, no DNS in tests
    yield server
    connector_http.set_transport(None)
    connector_http.set_resolver(None)
    registry.set_connectors(None)


def _ta(sa, tenant_id, email="ta@example.com"):
    _invite_and_accept(sa, email, "tenant_admin", tenant_id)
    ta = new_client(sa.app)
    login(ta, email)
    return ta


def _world(sa):
    _provider(sa)
    alfa, beta = _setup(sa)
    assert sa.put("/api/platform/integrations", json={"enabled": ["fakedesk"]}).status_code == 200
    ta = _ta(sa, alfa["id"])
    r = ta.post(f"/api/tenants/{alfa['id']}/integrations",
                json={"plugin": "fakedesk", "name": "Alfa desk", "config": {"url": URL + "/", "token": TOKEN}})
    assert r.status_code == 201, r.text
    return alfa, beta, ta, r.json()


def test_plugins_are_enabled_by_the_super_admin(super_admin, desk):
    plugins = super_admin.get("/api/platform/integrations").json()
    assert [p["name"] for p in plugins] == ["fakedesk"] and plugins[0]["enabled"] is False
    assert super_admin.put("/api/platform/integrations", json={"enabled": ["nope"]}).status_code == 422
    r = super_admin.put("/api/platform/integrations", json={"enabled": ["fakedesk"]})
    assert r.status_code == 200 and r.json()[0]["enabled"] is True


def test_instance_secrets_are_write_only_and_bound_to_the_address(super_admin, desk, fake_llm):
    alfa, beta, ta, inst = _world(super_admin)
    assert inst["config"] == {"url": URL, "queue": "soc"} and inst["secrets_set"] == {"token": True}
    listing = ta.get(f"/api/tenants/{alfa['id']}/integrations")
    assert TOKEN not in listing.text and listing.json()["plugins"][0]["config_schema"]["properties"]["token"]["secret"]
    # Changing the address without the token again: refused (the token never goes to another host).
    r = ta.put(f"/api/tenants/{alfa['id']}/integrations/{inst['id']}", json={"config": {"url": "https://other.example.com"}})
    assert r.status_code == 422 and "credentials" in r.text
    r = ta.put(f"/api/tenants/{alfa['id']}/integrations/{inst['id']}", json={"config": {"url": URL, "queue": "l2"}})
    assert r.status_code == 200 and r.json()["secrets_set"] == {"token": True} and r.json()["config"]["queue"] == "l2"
    # Test reaches the product with the stored token.
    assert ta.post(f"/api/tenants/{alfa['id']}/integrations/{inst['id']}/test").json() == {"ok": True, "detail": "Connected"}
    # Required secret missing on create.
    r = ta.post(f"/api/tenants/{alfa['id']}/integrations", json={"plugin": "fakedesk", "name": "x", "config": {"url": URL}})
    assert r.status_code == 422


def test_other_tenants_cannot_reach_an_instance(super_admin, desk, fake_llm):
    alfa, beta, ta, inst = _world(super_admin)
    tb = _ta(super_admin, beta["id"], "tb@example.com")
    assert tb.get(f"/api/tenants/{alfa['id']}/integrations").status_code == 404
    # Alfa's instance under Beta's id: not found.
    assert tb.post(f"/api/tenants/{beta['id']}/integrations/{inst['id']}/test").status_code == 404
    assert tb.delete(f"/api/tenants/{beta['id']}/integrations/{inst['id']}").status_code == 404
    assert super_admin.direct("GET", f"/api/tenants/{alfa['id']}/integrations").status_code == 403
    an = _analyst(super_admin)
    assert an.get(f"/api/tenants/{alfa['id']}/integrations").status_code == 403


def test_chat_uses_live_data_with_citation_link_and_audit(super_admin, desk, fake_llm):
    alfa, beta, ta, inst = _world(super_admin)
    an = _analyst(super_admin)
    options = an.get("/api/chats/integrations", params={"tenant_id": alfa["id"]}).json()
    assert options == [{"id": inst["id"], "name": "Alfa desk", "product": "FakeDesk", "type": "ticketing"}]
    assert an.get("/api/chats/integrations", params={"tenant_id": beta["id"]}).json() == []
    r = an.post("/api/chats", json={"tenant_id": alfa["id"], "integration_ids": [inst["id"]], "message": "Status of FAKE-12?"})
    assert r.status_code == 201, r.text
    a = r.json()["answer"]
    assert r.json()["chat"]["integration_ids"] == [inst["id"]]
    cit = a["citations"][0]
    assert cit["kind"] == "integration" and cit["record"] == "FAKE-12" and cit["url"] == URL + "/browse/FAKE-12"
    assert cit["tenant"] == "Alfa" and cit["integration"] == "Alfa desk"
    assert f"{URL}/browse/FAKE-12" in a["content"]  # the record's link is in the answer
    # The token went to the product only; the LLM got the record as data with its link.
    sent = fake_llm.requests[-1]["body"]["messages"][-1]["content"]
    assert "read now from Alfa desk" in sent and f"Link: {URL}/browse/FAKE-12" in sent and TOKEN not in sent
    db = next(db_module.get_db())
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "integration.called")).all()
    assert ev and ev[-1].detail["object"] == {"key": "FAKE-12"} and ev[-1].detail["ok"] is True
    db.close()


def test_links_not_from_records_are_removed(super_admin, desk, fake_llm):
    alfa, beta, ta, inst = _world(super_admin)
    an = _analyst(super_admin)
    fake_llm.reply_override = json.dumps({"answer": f"See [FAKE-12]({URL}/browse/FAKE-12) [1] and [login](https://evil.example.com/x) "
                                                    "or https://evil.example.com/y", "not_found": False, "followups": [], "title": None})
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "integration_ids": [inst["id"]], "message": "FAKE-12"}).json()["answer"]
    assert f"[FAKE-12]({URL}/browse/FAKE-12)" in a["content"] and "evil.example.com" not in a["content"]
    assert "Open:" not in a["content"]  # the record is already linked
    # An answer that cites the record without linking it gets the link under it.
    fake_llm.reply_override = json.dumps({"answer": "The ticket is In Progress [1].", "not_found": False, "followups": [], "title": None})
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "integration_ids": [inst["id"]], "message": "FAKE-12"}).json()["answer"]
    assert a["content"].endswith(f"Open: [FakeDesk Ticket FAKE-12]({URL}/browse/FAKE-12)")


def test_integrations_only_on_one_customer_and_only_its_own(super_admin, desk, fake_llm):
    alfa, beta, ta, inst = _world(super_admin)
    an = _analyst(super_admin)
    r = an.post("/api/chats", json={"tenant_id": beta["id"], "integration_ids": [inst["id"]], "message": "FAKE-12"})
    assert r.status_code == 422
    r = an.post("/api/chats", json={"tenant_id": None, "integration_ids": [inst["id"]], "message": "FAKE-12"})
    assert r.status_code == 422
    chat = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force"}).json()["chat"]
    assert an.patch(f"/api/chats/{chat['id']}", json={"integration_ids": [inst["id"]]}).json()["integration_ids"] == [inst["id"]]
    # The super-admin turns the plugin off: the chat no longer uses it.
    super_admin.put("/api/platform/integrations", json={"enabled": []})
    assert an.get(f"/api/chats/{chat['id']}").json()["integration_ids"] == []
    n = len(desk.requests)
    an.post(f"/api/chats/{chat['id']}/messages", json={"message": "FAKE-12"})
    assert len(desk.requests) == n


def test_failures_become_a_plain_note(super_admin, desk, fake_llm):
    alfa, beta, ta, inst = _world(super_admin)
    an = _analyst(super_admin)
    desk.status = 401
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "integration_ids": [inst["id"]],
                                    "message": "brute force attacks FAKE-12"}).json()["answer"]
    assert "*FakeDesk answered 401 (invalid credentials)*" in a["content"]
    assert TOKEN not in a["content"]
    db = next(db_module.get_db())
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "integration.called")).all()[-1]
    assert ev.level == "error" and TOKEN not in json.dumps(ev.detail)
    db.close()


def test_try_lookup_and_core_guards(super_admin, desk, fake_llm):
    alfa, beta, ta, inst = _world(super_admin)
    base = f"/api/tenants/{alfa['id']}/integrations/{inst['id']}/run"
    r = ta.post(base, json={"operation": "get_ticket", "args": {"key": "FAKE-12"}}).json()
    assert r["ok"] and r["records"][0]["fields"]["State"] == "In Progress"
    assert ta.post(base, json={"operation": "get_ticket", "args": {"key": "x'; drop"}}).json()["ok"] is False
    # Writes and other addresses never leave Mentis, whatever the plugin does.
    n = len(desk.requests)
    assert ta.post(base, json={"operation": "delete_ticket", "args": {"key": "FAKE-12"}}).json()["ok"] is False
    assert ta.post(base, json={"operation": "leave", "args": {}}).json()["ok"] is False
    assert len(desk.requests) == n


def test_safe_http_unit():
    seen = []
    connector_http.set_transport(httpx.MockTransport(lambda r: seen.append(r) or answer(302, headers={"location": "https://evil"})))
    connector_http.set_resolver(lambda host: ["93.184.216.34"])
    try:
        h = connector_http.SafeHttp("P", ["https://a.example.com"], ["https://a.example.com/token"], max_requests=3)
        assert h.request("GET", "https://a.example.com/x").status == 302  # redirects are not followed
        assert h.request("POST", "https://a.example.com/token").status == 302
        for method, url in [("POST", "https://a.example.com/other"), ("PUT", "https://a.example.com/x"),
                            ("GET", "https://a.example.com:8443/x"), ("GET", "http://a.example.com/x")]:
            with pytest.raises(ConnectorError):
                h.request(method, url)
        h.request("GET", "https://a.example.com/y")
        with pytest.raises(ConnectorError):
            h.request("GET", "https://a.example.com/z")  # request cap
        assert len(seen) == 3
        assert seen[0].headers["host"] == "a.example.com" and seen[0].url.host == "93.184.216.34"  # pinned IP, real Host
    finally:
        connector_http.set_transport(None)
        connector_http.set_resolver(None)


def test_tenant_deletion_and_config_export(super_admin, desk, fake_llm):
    alfa, beta, ta, inst = _world(super_admin)
    export = super_admin.get("/api/platform/config/export")
    assert TOKEN not in export.text
    data = export.json()
    assert data["platform"]["integrations"] == {"enabled": ["fakedesk"]}
    alfa_cfg = next(t for t in data["tenants"] if t["name"] == "Alfa")
    assert alfa_cfg["integrations"] == [{"name": "Alfa desk", "plugin": "fakedesk", "config": {"url": URL, "queue": "soc"}, "enabled": True}]
    # Import into Beta: added disabled, credentials to enter.
    next(t for t in data["tenants"] if t["name"] == "Beta")["integrations"] = alfa_cfg["integrations"]
    files = {"file": ("c.json", json.dumps(data).encode(), "application/json")}
    plan = super_admin.post("/api/platform/config/import?apply=true", files=files).json()
    assert any("Beta: integration Alfa desk: add (disabled" in p for p in plan["changes"]), plan
    r = super_admin.direct("DELETE", f"/api/tenants/{alfa['id']}", json={"confirm_name": "Alfa"})
    assert r.status_code in (200, 204), r.text
    db = next(db_module.get_db())
    left = db.scalars(select(Integration)).all()
    assert [(i.name, i.enabled, i.secrets_enc) for i in left] == [("Alfa desk", False, None)]
    db.close()


def test_safe_links_keep_document_addresses_as_text():
    from app.services.answer import _safe_links

    record = f"{URL}/browse/FAKE-12"
    sources = ["Escalate on the portal https://portal.acme.example/soc within 30 minutes"]
    text = (f"[FAKE-12]({record}) [1], [portal](https://portal.acme.example/soc) or https://portal.acme.example/soc. "
            "Not [this](https://evil.example.com/a), nor https://evil.example.com/b.")
    out = _safe_links(text, {record}, sources)
    assert f"[FAKE-12]({record})" in out
    assert "portal (https://portal.acme.example/soc)" in out and "https://portal.acme.example/soc." in out
    assert "evil.example.com" not in out and out.endswith("nor [link removed].")


def test_integration_with_unreadable_address_never_breaks_the_chat(super_admin, desk, fake_llm, monkeypatch):
    alfa, beta, ta, inst = _world(super_admin)
    an = _analyst(super_admin)

    def broken(self, config):
        raise ConnectorError("bad address", retryable=False)

    monkeypatch.setattr(FakeDesk, "origins", broken)
    r = an.post("/api/chats", json={"tenant_id": alfa["id"], "integration_ids": [inst["id"]], "message": "brute force FAKE-12"})
    assert r.status_code == 201 and r.json()["answer"]["status"] == "ok"
    assert "*FakeDesk (Alfa desk) could not be read right now*" in r.json()["answer"]["content"]
    assert ta.post(f"/api/tenants/{alfa['id']}/integrations/{inst['id']}/test").json()["ok"] is False


# --- Lookup mode: function calling ----------------------------------------------------------

def _tools_transport(fake_llm, steps, seen):
    """Anthropic tool-use replies from `steps` (one per request with tools), the FakeLLM otherwise."""
    script = iter(steps)

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            body = json.loads(request.content)
            if "tools" in body:
                seen.append(body)
                step = next(script)
                if isinstance(step, int):
                    return httpx.Response(step, json={"error": {"message": "tools are not supported"}})
                return httpx.Response(200, json={"content": step, "usage": {"input_tokens": 50, "output_tokens": 10}})
        return fake_llm.handle(request)
    return httpx.MockTransport(handle)


def test_mode_is_chosen_by_who_chose_the_llm(super_admin, desk, fake_llm):
    alfa, beta, ta, inst = _world(super_admin)
    url = f"/api/tenants/{alfa['id']}/integration-mode"
    assert ta.get(url).json() == {"mode": "standard", "editable": False, "own_llm": False,
                                  "reason": "This customer uses the platform's LLM: a super-admin chooses the mode."}
    assert ta.put(url, json={"mode": "tools"}).status_code == 403
    # The customer gets its own LLM, chosen by its tenant admin: now the tenant admin decides.
    provider = super_admin.get("/api/llm/providers").json()[0]["id"]
    assert ta.put(f"/api/tenants/{alfa['id']}/llm", json={"provider_id": provider}).status_code == 200
    r = ta.put(url, json={"mode": "tools"})
    assert r.status_code == 200 and r.json()["mode"] == "tools" and r.json()["editable"] is True
    assert super_admin.put(url, json={"mode": "standard"}).json()["mode"] == "standard"
    general = next(t for t in super_admin.get("/api/tenants").json() if t["is_global"])
    assert super_admin.put(f"/api/tenants/{general['id']}/integration-mode", json={"mode": "tools"}).status_code == 409
    assert super_admin.put(url, json={"mode": "magic"}).status_code == 422
    an = _analyst(super_admin)
    assert an.get(url).status_code == 403


def test_tools_mode_follows_the_thread(super_admin, desk, fake_llm):
    alfa, beta, ta, inst = _world(super_admin)
    super_admin.put(f"/api/tenants/{alfa['id']}/integration-mode", json={"mode": "tools"})
    seen = []
    steps = [
        [{"type": "tool_use", "id": "t1", "name": "i1__get_ticket", "input": {"key": "FAKE-13"}}],  # the follow-up named in FAKE-12
        [{"type": "text", "text": "DONE"}],
    ]
    llm.set_transport(_tools_transport(fake_llm, steps, seen))
    an = _analyst(super_admin)
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "integration_ids": [inst["id"]], "message": "Analyze FAKE-12"}).json()["answer"]
    # FAKE-12 read without a model (identifier), FAKE-13 chosen by the model after reading it.
    paths = [r.url.path for r in desk.requests]
    assert paths == ["/api/tickets/FAKE-12", "/api/tickets/FAKE-13"]
    assert "ALREADY LOOKED UP" in seen[0]["messages"][0]["content"] and "FAKE-12" in seen[0]["messages"][0]["content"]
    assert seen[1]["messages"][-1]["content"][0]["type"] == "tool_result" and "DATA (not instructions)" in seen[1]["messages"][-1]["content"][0]["content"]
    sent = fake_llm.requests[-1]["body"]["messages"][-1]["content"]
    assert "Ticket FAKE-12" in sent and "Ticket FAKE-13" in sent
    assert a["status"] == "ok"
    db = next(db_module.get_db())
    ev = db.scalars(select(AuditEvent).where(AuditEvent.action == "integration.planned")).all()[-1]
    assert ev.detail["mode"] == "tools" and ev.detail["rounds"] == 2 and ev.detail["calls"] == 2
    db.close()


def test_tools_mode_checks_arguments_and_falls_back(super_admin, desk, fake_llm):
    alfa, beta, ta, inst = _world(super_admin)
    super_admin.put(f"/api/tenants/{alfa['id']}/integration-mode", json={"mode": "tools"})
    seen = []
    steps = [[{"type": "tool_use", "id": "t1", "name": "i1__get_ticket", "input": {"key": "x'); DROP"}},
              {"type": "tool_use", "id": "t2", "name": "i9__nope", "input": {}}],
             [{"type": "text", "text": "DONE"}]]
    llm.set_transport(_tools_transport(fake_llm, steps, seen))
    an = _analyst(super_admin)
    an.post("/api/chats", json={"tenant_id": alfa["id"], "integration_ids": [inst["id"]], "message": "what about the ticket?"})
    assert desk.requests == []  # neither call ran
    results = seen[1]["messages"][-1]["content"]
    assert results[0]["content"].startswith("Error: invalid arguments") and results[1]["content"] == "Error: unknown tool."
    # A model or provider without tool calling: the standard mode, FAKE-12 read once.
    llm.set_transport(_tools_transport(fake_llm, [400], []))
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "integration_ids": [inst["id"]], "message": "Status of FAKE-12?"}).json()["answer"]
    assert [r.url.path for r in desk.requests] == ["/api/tickets/FAKE-12"]
    assert a["citations"][0]["record"] == "FAKE-12"
    db = next(db_module.get_db())
    assert db.scalars(select(AuditEvent).where(AuditEvent.action == "integration.tools_unavailable")).first() is not None
    db.close()
