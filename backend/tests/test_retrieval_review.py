"""Regression tests for the index and retrieval review of 0.6.2 (docs/security/review-v0.6.2.md, R-1..R-8)."""

import json

import httpx
import pytest
from sqlalchemy import select

from app.core import db as db_module
from app.models import ChatMessage, Document
from app.services import embeddings, vector_index, versions
from tests.conftest import run_jobs
from tests.http_mock import answer
from tests.test_access import _user
from tests.test_chat import _provider, fake_llm  # noqa: F401 - fixture
from tests.test_indexing import _docx, _tenant, _upload

SECRET = "VAULTPW-Kx9-2026"


def _world(c, text=f"Brute force attacks: the vault password is {SECRET}"):
    _provider(c)
    beta = _tenant(c, "Beta")
    _upload(c, beta["id"], "Mistake.docx", _docx(text))
    run_jobs(c)
    return beta, _user(c, "an@example.com", "analyst", tenant_ids=[beta["id"]])


def _delete_doc(name="Mistake.docx"):
    db = next(db_module.get_db())
    doc = db.scalar(select(Document).where(Document.name == name))
    if doc is not None:
        versions.delete_document(db, doc)
    db.close()


def test_document_deleted_while_the_answer_is_written_is_removed(super_admin, fake_llm):  # noqa: F811
    beta, an = _world(super_admin)
    orig = fake_llm.answer_for
    fake_llm.answer_for = lambda body: (_delete_doc(), orig(body))[1]
    ex = an.post("/api/chats", json={"tenant_id": beta["id"], "message": "brute force attacks vault password"}).json()
    got = an.get(f"/api/chats/{ex['chat']['id']}").json()["messages"][1]
    assert SECRET not in json.dumps(got)
    db = next(db_module.get_db())
    assert all(SECRET not in (m.content or "") for m in db.scalars(select(ChatMessage)))
    db.close()


def test_background_check_never_brings_back_a_removed_answer(super_admin, fake_llm):  # noqa: F811
    from app.services.answer_check import runner

    beta, an = _world(super_admin)
    real = runner._run_level2

    def slow(cfg, result):
        _delete_doc()  # the document goes while level 2 runs
        return [{"level": [2], "kind": "statement", "text": f"the vault password is {SECRET}", "reason": "x"}], "ok", None
    runner._run_level2 = slow
    try:
        ex = an.post("/api/chats", json={"tenant_id": beta["id"], "message": "brute force attacks vault password"}).json()
    finally:
        runner._run_level2 = real
    got = an.get(f"/api/chats/{ex['chat']['id']}").json()
    assert SECRET not in json.dumps(got)


def test_uncited_passages_and_titles_of_a_deleted_document_do_not_survive(super_admin, fake_llm):  # noqa: F811
    beta, an = _world(super_admin)
    fake_llm.reply_override = json.dumps({"answer": f"The password is {SECRET}.", "not_found": False,
                                          "followups": [f"Rotate {SECRET}?"], "title": f"Vault {SECRET}"})
    ex = an.post("/api/chats", json={"tenant_id": beta["id"], "message": "vault password brute force attacks"}).json()
    fake_llm.reply_override = None
    assert SECRET not in ex["chat"]["title"]  # the title is the question
    _delete_doc()
    assert SECRET not in json.dumps(an.get(f"/api/chats/{ex['chat']['id']}").json())
    assert SECRET not in json.dumps(an.get("/api/chats").json())


def _transport(monkeypatch, handler):
    real = httpx.Client

    def client(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)
    monkeypatch.setattr(embeddings.httpx, "Client", client)
    embeddings.set_embedder(None)


def test_stored_embedding_key_never_follows_a_new_address(super_admin, monkeypatch):
    seen = []

    def handle(request):
        seen.append((request.url.host, request.headers.get("authorization")))
        n = len(json.loads(request.content)["input"])
        return answer(200, json={"data": [{"index": i, "embedding": [0.1, 0.2, 0.3]} for i in range(n)]})
    _transport(monkeypatch, handle)
    assert super_admin.put("/api/platform/embedding", json={"url": "https://emb.example/v1", "model": "m",
                                                             "api_key": "sk-EMBED"}).status_code == 200
    r = super_admin.put("/api/platform/embedding", json={"url": "https://other.example/v1"})
    assert r.status_code == 200 and r.json()["api_key_set"] is False  # the key stays with its address
    super_admin.put("/api/platform/embedding", json={"url": "https://emb.example/v1", "api_key": "sk-EMBED"})
    data = {"format": "mentis-config/1", "tenants": [], "llm_providers": [],
            "platform": {"embedding": {"url": "https://import.example/v1", "model": "m"}}}
    r = super_admin.post("/api/platform/config/import?apply=true", files={"file": ("c.json", json.dumps(data).encode())})
    assert r.status_code == 200, r.text
    super_admin.post("/api/platform/embedding/test")
    assert ("import.example", "Bearer sk-EMBED") not in seen and seen[-1] == ("import.example", None)


def test_embedding_addresses_can_be_pinned(super_admin, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "embedding_allowed_urls", "https://emb.example")
    r = super_admin.put("/api/platform/embedding", json={"url": "https://attacker.example/v1", "api_key": ""})
    assert r.status_code == 422 and "MENTIS_EMBEDDING_ALLOWED_URLS" in r.json()["detail"]
    assert super_admin.put("/api/platform/embedding", json={"url": "https://emb.example/v2", "api_key": ""}).status_code == 200


@pytest.mark.parametrize("body", [
    {"data": [{"index": 0, "embedding": [float("nan"), 0.1]}]},
    {"data": [{"index": 0, "embedding": [0.1, 0.2]}, {"index": 1, "embedding": [0.1]}]},
    {"data": [{"index": 0, "embedding": [0.1]}, {"index": 0, "embedding": [0.2]}]},
    {"data": [{"index": 0, "embedding": ["a", None]}]},
])
def test_embedding_answers_are_validated(monkeypatch, body):
    n = len(body["data"])
    _transport(monkeypatch, lambda r: answer(200, content=json.dumps(body, allow_nan=True).encode(),
                                             headers={"content-type": "application/json"}))
    with pytest.raises(embeddings.EmbeddingError):
        embeddings.embed({"url": "https://emb.example/v1", "model": "m", "api_key": None}, ["x"] * n)


def test_reindex_failing_while_clearing_keeps_answers_paused(super_admin, fake_llm, monkeypatch):  # noqa: F811
    _world(super_admin)
    monkeypatch.setattr(vector_index, "delete_tenant", lambda tid: (_ for _ in ()).throw(RuntimeError("timed out")))
    assert super_admin.post("/api/platform/embedding/reindex").status_code == 202
    run_jobs(super_admin)
    state = super_admin.get("/api/platform/embedding").json()["reindex"]
    assert state["status"] == "failed" and state["blocking"]
