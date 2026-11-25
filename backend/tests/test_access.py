"""0.3.0 access model: tenants ticked per user, all_tenants, General, super-admin without content."""

import pytest

from app.services import llm
from tests import samples
from tests.conftest import login, new_client, run_jobs
from tests.fake_llm import FakeLLM
from tests.test_chat import _provider
from tests.test_indexing import _docx, _general, _tenant, _upload
from tests.test_tenants_users import _invite_and_accept


@pytest.fixture
def fake_llm():
    f = FakeLLM()
    llm.set_transport(f.transport())
    yield f
    llm.set_transport(None)


def _user(sa, email, role, **kw):
    _invite_and_accept(sa, email, role, **kw)
    c = new_client(sa.app)
    c.secret = login(c, email)
    return c


def _world(sa):
    alfa, beta = _tenant(sa, "Alfa"), _tenant(sa, "Beta")
    g = _general(sa)
    _upload(sa, alfa["id"], "Escalation.docx", _docx("Escalate brute force attacks to Mario Rossi phone 111"))
    _upload(sa, beta["id"], "Escalation.docx", _docx("Escalate brute force attacks to Anna Verdi phone 222"))
    _upload(sa, g["id"], "Runbook.docx", _docx("Brute force attacks: lock the account first, then escalate"))
    run_jobs(sa)
    return alfa, beta, g


def test_super_admin_sees_no_content(super_admin, fake_llm):
    alfa, _, g = _world(super_admin)
    sa = super_admin.direct
    assert sa("GET", f"/api/tenants/{alfa['id']}/documents").status_code == 404
    assert sa("GET", f"/api/tenants/{g['id']}/documents").status_code == 404
    assert sa("POST", f"/api/tenants/{g['id']}/documents", files={"file": ("x.docx", samples.docx())}).status_code == 404
    assert sa("GET", "/api/chats").status_code == 403
    assert sa("GET", "/api/chats/scopes").status_code == 403
    assert sa("POST", "/api/chats", json={"tenant_id": None, "message": "x"}).status_code == 403
    assert super_admin.direct("GET", "/api/auth/me").json()["tenants"] == []
    # It still manages tenants and their LLM.
    assert super_admin.get(f"/api/tenants/{alfa['id']}").status_code == 200
    assert super_admin.get(f"/api/tenants/{alfa['id']}/llm").status_code == 200


def test_analyst_sees_only_its_customers(super_admin, fake_llm):
    _provider(super_admin)
    alfa, beta, g = _world(super_admin)
    an = _user(super_admin, "an@example.com", "analyst", tenant_ids=[alfa["id"], g["id"]])
    assert [s["name"] for s in an.get("/api/chats/scopes").json()] == ["Alfa"]
    assert an.post("/api/chats", json={"tenant_id": beta["id"], "message": "x"}).status_code == 403
    an.post("/api/chats", json={"tenant_id": None, "message": "brute force attacks escalate"})
    sent = fake_llm.requests[-1]["body"]["messages"][-1]["content"]
    assert "Mario Rossi" in sent and "Anna Verdi" not in sent and "lock the account" in sent  # General included
    # Without General ticked, General is not searched.
    an2 = _user(super_admin, "an2@example.com", "analyst", tenant_ids=[alfa["id"]])
    an2.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force attacks escalate"})
    assert "lock the account" not in fake_llm.requests[-1]["body"]["messages"][-1]["content"]


def test_all_customers_includes_future_ones(super_admin, fake_llm):
    _provider(super_admin)
    _world(super_admin)
    an = _user(super_admin, "an@example.com", "analyst", all_tenants=True)
    assert [s["name"] for s in an.get("/api/chats/scopes").json()] == ["All customers", "Alfa", "Beta"]
    _tenant(super_admin, "Gamma")
    assert "Gamma" in [s["name"] for s in an.get("/api/chats/scopes").json()]
    # A ticked analyst does not get the new customer.
    alfa = next(t for t in super_admin.get("/api/tenants").json() if t["name"] == "Alfa")
    an2 = _user(super_admin, "an2@example.com", "analyst", tenant_ids=[alfa["id"]])
    assert "Gamma" not in [s["name"] for s in an2.get("/api/chats/scopes").json()]


def test_removing_a_customer_makes_its_chats_read_only(super_admin, fake_llm):
    _provider(super_admin)
    alfa, beta, g = _world(super_admin)
    an = _user(super_admin, "an@example.com", "analyst", tenant_ids=[alfa["id"], beta["id"]])
    cid = an.post("/api/chats", json={"tenant_id": beta["id"], "message": "brute force"}).json()["chat"]["id"]
    uid = next(u["id"] for u in super_admin.get("/api/users").json() if u["email"] == "an@example.com")
    super_admin.patch(f"/api/users/{uid}", json={"tenant_ids": [alfa["id"]]})
    assert an.get("/api/auth/me").status_code == 401  # tenant changes end the sessions
    import time

    import pyotp

    from tests.conftest import PASSWORD

    ch = an.post("/api/auth/login", json={"email": "an@example.com", "password": PASSWORD}).json()["challenge"]
    assert an.post("/api/auth/totp/verify", json={"challenge": ch, "code": pyotp.TOTP(an.secret).at(time.time() + 30)}).status_code == 200
    assert an.get(f"/api/chats/{cid}").json()["scope_available"] is False
    assert an.post(f"/api/chats/{cid}/messages", json={"message": "again"}).status_code == 409


def test_tenant_admin_invites_analysts_within_its_customers(super_admin):
    alfa, beta, g = _world(super_admin)
    ta = _user(super_admin, "ta@example.com", "tenant_admin", tenant_ids=[alfa["id"], g["id"]])
    ok = ta.post("/api/invitations", json={"email": "a1@example.com", "full_name": "A1", "role": "analyst", "tenant_ids": [alfa["id"], g["id"]]})
    assert ok.status_code == 201
    assert ta.post("/api/invitations", json={"email": "a2@example.com", "full_name": "A2", "role": "analyst", "tenant_ids": [beta["id"]]}).status_code == 403
    # Users it cannot manage are not even listed.
    _invite_and_accept(super_admin, "other@example.com", "analyst", tenant_ids=[alfa["id"], beta["id"]])
    _invite_and_accept(super_admin, "mine@example.com", "analyst", tenant_ids=[alfa["id"]])
    emails = {u["email"] for u in ta.get("/api/users").json()}
    assert "mine@example.com" in emails and "other@example.com" not in emails and "admin@example.com" not in emails
    mine = next(u for u in ta.get("/api/users").json() if u["email"] == "mine@example.com")
    assert ta.patch(f"/api/users/{mine['id']}", json={"role": "tenant_admin"}).status_code == 200
    assert ta.patch(f"/api/users/{mine['id']}", json={"tenant_ids": [beta["id"]]}).status_code == 403
    assert ta.patch(f"/api/users/{mine['id']}", json={"all_tenants": True}).status_code == 403
    me = ta.get("/api/auth/me").json()
    assert ta.patch(f"/api/users/{me['id']}", json={"tenant_ids": [alfa["id"]]}).status_code == 403


def test_tenant_admin_of_all_customers_can_give_all(super_admin):
    _world(super_admin)
    boss = _user(super_admin, "boss@example.com", "tenant_admin", all_tenants=True)
    r = boss.post("/api/invitations", json={"email": "x@example.com", "full_name": "X", "role": "analyst", "all_tenants": True})
    assert r.status_code == 201 and r.json()["all_tenants"] is True


def test_tenant_admin_with_general_manages_it(super_admin):
    _, _, g = _world(super_admin)
    ta = _user(super_admin, "ta@example.com", "tenant_admin", tenant_ids=[g["id"]])
    assert [d["name"] for d in ta.get(f"/api/tenants/{g['id']}/documents").json()] == ["Runbook.docx"]
    assert _upload(ta, g["id"], "Shared.docx", samples.docx())["status"] in ("queued", "processing", "ready")


def test_llm_choice_allowed_per_tenant_and_minimal_provider_view(super_admin, fake_llm):
    p = _provider(super_admin, options={"price_in": 1.0, "price_out": 2.0})
    alfa, _, _ = _world(super_admin)
    ta = _user(super_admin, "ta@example.com", "tenant_admin", tenant_ids=[alfa["id"]])
    providers = ta.get("/api/llm/providers").json()
    assert providers == [{"id": p["id"], "name": "Claude", "kind": None, "base_url": None, "model": "claude-haiku-5-5",
                          "api_key_set": None, "options": None, "is_default": True}]
    assert ta.put(f"/api/tenants/{alfa['id']}/llm", json={"provider_id": p["id"]}).status_code == 200
    # The super-admin takes the choice away; the tenant admin cannot give it back.
    assert ta.patch(f"/api/tenants/{alfa['id']}", json={"settings": {"admin_can_set_llm": True}}).status_code == 403
    super_admin.patch(f"/api/tenants/{alfa['id']}", json={"settings": {"admin_can_set_llm": False}})
    assert ta.get(f"/api/tenants/{alfa['id']}/llm").json()["editable"] is False
    assert ta.put(f"/api/tenants/{alfa['id']}/llm", json={"provider_id": None}).status_code == 403
    assert super_admin.put(f"/api/tenants/{alfa['id']}/llm", json={"provider_id": None}).status_code == 200
    # Usage without costs for the tenant admin.
    ta.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force attacks escalate"})
    u = ta.get("/api/usage").json()
    assert u["totals"]["questions"] == 1 and u["totals"]["cost_usd"] is None and u["rows"][0]["cost_usd"] is None
    assert super_admin.get("/api/usage").json()["totals"]["cost_usd"] is not None
