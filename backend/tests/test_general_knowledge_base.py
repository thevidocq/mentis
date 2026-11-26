"""General Knowledge Base: everyone reads it, only explicit managers change it, always approved."""

from tests.conftest import run_jobs
from tests.test_access import _user
from tests.test_chat import _provider, fake_llm  # noqa: F401 - fixture
from tests.test_indexing import _docx, _general, _tenant


def _up(c, tid, name, text):
    return c.post(f"/api/tenants/{tid}/documents", files={"file": (name, _docx(text))})


def test_managing_needs_the_explicit_tick_and_approval(super_admin, fake_llm):  # noqa: F811
    _provider(super_admin)
    alfa, g = _tenant(super_admin, "Alfa"), _general(super_admin)
    assert g["name"] == "General Knowledge Base"
    every = _user(super_admin, "every@example.com", "tenant_admin", all_tenants=True)
    kb = _user(super_admin, "kb@example.com", "tenant_admin", tenant_ids=[g["id"]])
    # All customers does not include managing the GKB.
    assert _up(every, g["id"], "KB.docx", "x").status_code == 404
    assert every.get("/api/auth/me").json()["can_manage_general"] is False
    assert all(not t["is_global"] for t in every.get("/api/tenants").json())
    # The manager uploads; the version waits for approval and is not used until approved.
    v = _up(kb, g["id"], "Phishing.docx", "Phishing triage: check the mail headers first").json()
    run_jobs(super_admin)
    got = kb.get(f"/api/tenants/{g['id']}/documents/versions/{v['id']}").json()
    assert got["approval"] == "pending" and got["is_active"] is False
    an = _user(super_admin, "an@example.com", "analyst", tenant_ids=[alfa["id"]])
    a = an.post("/api/chats", json={"tenant_id": g["id"], "message": "phishing triage mail headers"}).json()["answer"]
    assert a["status"] == "not_found"
    assert kb.post(f"/api/tenants/{g['id']}/documents/versions/{v['id']}/approve").status_code == 200
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "phishing triage mail headers"}).json()["answer"]
    assert a["status"] == "ok" and any(c["is_general"] for c in a["citations"])  # read with the customer, no tick


def test_only_managers_hand_out_management(super_admin):
    alfa, g = _tenant(super_admin, "Alfa"), _general(super_admin)
    ta = _user(super_admin, "ta@example.com", "tenant_admin", tenant_ids=[alfa["id"]])
    kb = _user(super_admin, "kb@example.com", "tenant_admin", tenant_ids=[alfa["id"], g["id"]])
    body = {"email": "new@example.com", "full_name": "New", "role": "tenant_admin", "tenant_ids": [alfa["id"], g["id"]]}
    assert ta.post("/api/invitations", json=body).status_code == 403
    assert kb.post("/api/invitations", json=body).status_code == 201
    # For an analyst the tick is meaningless: it is dropped, and the analyst still reads the GKB.
    an = _user(super_admin, "an@example.com", "analyst", tenant_ids=[alfa["id"], g["id"]])
    me = an.get("/api/auth/me").json()
    assert {t["name"] for t in me["tenants"]} == {"Alfa", "General Knowledge Base"} and me["can_manage_general"] is False
    users = {u["email"]: u for u in super_admin.get("/api/users").json()}
    assert [t["name"] for t in users["an@example.com"]["tenants"]] == ["Alfa"]
