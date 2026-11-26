"""Regression tests for the isolation fixes found by the authorization review (see CHANGELOG, Security)."""

import time

import pyotp

from app.services import embeddings
from app.services.chat_visibility import HIDDEN
from tests import fake_embeddings
from tests.conftest import PASSWORD, run_jobs
from tests.test_access import _user
from tests.test_chat import _provider, fake_llm  # noqa: F401 - fixture
from tests.test_indexing import _docx, _general, _tenant, _upload


def _relogin(c, email):
    """Sign in again after the sessions were revoked (the TOTP step of the first login is used)."""
    ch = c.post("/api/auth/login", json={"email": email, "password": PASSWORD}).json()["challenge"]
    r = c.post("/api/auth/totp/verify", json={"challenge": ch, "code": pyotp.TOTP(c.secret).at(time.time() + 30)})
    assert r.status_code == 200, r.text


def test_answers_of_a_customer_removed_from_the_user_are_hidden(super_admin, fake_llm):  # noqa: F811
    _provider(super_admin)
    alfa, beta = _tenant(super_admin, "Alfa"), _tenant(super_admin, "Beta")
    _upload(super_admin, alfa["id"], "Alfa.docx", _docx("Alfa phishing triage: check the mail headers"))
    _upload(super_admin, beta["id"], "Beta.docx", _docx("BETASECRET brute force attacks escalate to Anna Verdi"))
    run_jobs(super_admin)
    email = "an@example.com"
    an = _user(super_admin, email, "analyst", tenant_ids=[alfa["id"], beta["id"]])

    every = an.post("/api/chats", json={"tenant_id": None, "message": "brute force attacks escalate"}).json()
    assert "BETASECRET" in every["answer"]["content"] and every["answer"]["citations"][0]["tenant_id"] == beta["id"]
    on_beta = an.post("/api/chats", json={"tenant_id": beta["id"], "message": "brute force attacks escalate"}).json()
    on_alfa = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "phishing triage mail headers"}).json()

    uid = next(u["id"] for u in super_admin.get("/api/users").json() if u["email"] == email)
    assert super_admin.patch(f"/api/users/{uid}", json={"tenant_ids": [alfa["id"]]}).status_code == 200
    _relogin(an, email)

    for chat in (every, on_beta):
        got = an.get(f"/api/chats/{chat['chat']['id']}").json()
        answer = got["messages"][1]
        assert answer["content"] == HIDDEN and answer["citations"] == [] and answer["followups"] == []
        assert "BETASECRET" not in str(got) and "Beta.docx" not in str(got)
        assert got["messages"][0]["content"] == "brute force attacks escalate"  # the user's own question stays
        # Feedback answers with the message: hidden as well.
        r = an.post(f"/api/chats/{chat['chat']['id']}/messages/{answer['id']}/feedback", json={"value": 1})
        assert r.status_code == 200 and "BETASECRET" not in r.text
    # Answers on a customer still assigned stay readable.
    kept = an.get(f"/api/chats/{on_alfa['chat']['id']}").json()["messages"][1]
    assert kept["content"] != HIDDEN and kept["citations"]

    # The hidden answer is not sent back to the LLM as history of the "All my customers" chat.
    fake_llm.requests.clear()
    r = an.post(f"/api/chats/{every['chat']['id']}/messages", json={"message": "phishing triage mail headers and who to call"})
    assert r.status_code == 200
    assert fake_llm.requests and "BETASECRET" not in str(fake_llm.requests[-1]["body"])


def test_answers_saved_before_citations_carried_the_tenant_id_are_checked_by_name(super_admin, fake_llm):  # noqa: F811
    from app.core import db as db_module
    from app.models import ChatMessage

    _provider(super_admin)
    alfa, beta = _tenant(super_admin, "Alfa"), _tenant(super_admin, "Beta")
    _upload(super_admin, beta["id"], "Beta.docx", _docx("BETASECRET brute force attacks escalate"))
    run_jobs(super_admin)
    an = _user(super_admin, "an@example.com", "analyst", tenant_ids=[alfa["id"], beta["id"]])
    chat = an.post("/api/chats", json={"tenant_id": None, "message": "brute force attacks escalate"}).json()
    db = next(db_module.get_db())
    m = db.get(ChatMessage, __import__("uuid").UUID(chat["answer"]["id"]))
    m.citations = [{k: v for k, v in c.items() if k != "tenant_id"} for c in m.citations]  # as saved by 0.3.1
    db.commit()
    db.close()
    uid = next(u["id"] for u in super_admin.get("/api/users").json() if u["email"] == "an@example.com")
    super_admin.patch(f"/api/users/{uid}", json={"tenant_ids": [alfa["id"]]})
    _relogin(an, "an@example.com")
    assert an.get(f"/api/chats/{chat['chat']['id']}").json()["messages"][1]["content"] == HIDDEN


def test_service_errors_do_not_reveal_internal_details_to_users(super_admin, fake_llm):  # noqa: F811
    _provider(super_admin)
    alfa = _tenant(super_admin, "Alfa")
    v = _upload(super_admin, alfa["id"], "A.docx", _docx("Escalate brute force attacks to Mario Rossi"))
    run_jobs(super_admin)
    an = _user(super_admin, "an@example.com", "analyst", tenant_ids=[alfa["id"], _general(super_admin)["id"]])

    # LLM provider answering with an error body: no status, body or provider address for the analyst.
    fake_llm.fail["api.anthropic.com"] = 500
    a = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"}).json()["answer"]
    assert a["status"] == "error" and "AI provider did not answer" in a["content"]
    assert "boom" not in a["content"] and "500" not in a["content"] and "anthropic.com" not in a["content"]
    fake_llm.fail.clear()

    # Embedding service down: its internal address stays in the logs (super-admin only).
    def down(_texts):
        raise embeddings.EmbeddingError("Embedding service not reachable at http://tei-internal:80: ConnectError")

    embeddings.set_embedder(down)
    try:
        a = an.post("/api/chats", json={"tenant_id": alfa["id"], "message": "brute force escalation"}).json()["answer"]
        assert a["status"] == "error" and "tei-internal" not in a["content"]
        r = super_admin.post(f"/api/tenants/{alfa['id']}/documents/versions/{v['id']}/search", json={"question": "brute force"})
        assert r.status_code == 503 and "tei-internal" not in r.text
        failed = _upload(super_admin, alfa["id"], "B.docx", _docx("Another procedure"))
        run_jobs(super_admin)
        got = super_admin.get(f"/api/tenants/{alfa['id']}/documents/versions/{failed['id']}").json()
        assert got["status"] == "failed" and got["error"].startswith("Indexing failed") and "tei-internal" not in got["error"]
    finally:
        embeddings.set_embedder(fake_embeddings.embed)
    logs = super_admin.get("/api/logs", params={"q": ""}).text
    assert "tei-internal" in logs  # the super-admin still sees the cause
