import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from qdrant_client import models

from app.core import db as db_module
from app.services import embeddings, retrieval, vector_index
from tests import fake_embeddings
from tests.conftest import PASSWORD, approve_general, login, new_client, run_jobs


def _db():
    return next(db_module.get_db())


def _tenant(c, name):
    return c.post("/api/tenants", json={"name": name}).json()


def _general(c):
    return next(t for t in c.get("/api/tenants").json() if t["is_global"])


def _upload(c, tenant_id, filename, data):
    r = c.post(f"/api/tenants/{tenant_id}/documents", files={"file": (filename, data, "application/octet-stream")})
    assert r.status_code == 201, r.text
    return r.json()


def _docx(*paragraphs) -> bytes:
    import io

    import docx

    d = docx.Document()
    d.add_heading("Procedure", level=1)
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _ask(tenant_ids, question):
    return retrieval.search_tenants(_db(), [uuid.UUID(t) for t in tenant_ids], question, limit=5)


def _points(tenant_id):
    name = vector_index.collection_name(tenant_id)
    c = vector_index.client()
    if not c.collection_exists(name):
        return []
    return c.scroll(name, limit=1000, with_payload=True)[0]


# --- Indexing and versions -----------------------------------------------------

def test_ready_version_is_indexed_and_searchable(super_admin):
    t = _tenant(super_admin, "Alfa")
    v = _upload(super_admin, t["id"], "Escalation.docx", _docx("Escalate brute force attacks to Mario Rossi on call"))
    run_jobs(super_admin)
    v = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v['id']}").json()
    assert v["status"] == "ready" and v["stats"]["chunks"] >= 1
    pts = _points(t["id"])
    assert pts and all(p.payload["active"] for p in pts)
    hits = _ask([t["id"]], "who handles brute force escalation")
    assert hits and "Mario Rossi" in hits[0].text
    assert hits[0].document_name == "Escalation.docx" and hits[0].page_label


def test_new_version_replaces_old_in_answers_and_restore(super_admin):
    t = _tenant(super_admin, "Alfa")
    v1 = _upload(super_admin, t["id"], "Contacts.docx", _docx("On call contact is Mario Rossi"))
    run_jobs(super_admin)
    _upload(super_admin, t["id"], "Contacts.docx", _docx("On call contact is Anna Verdi"))
    run_jobs(super_admin)
    hits = _ask([t["id"]], "on call contact")
    assert hits and all("Anna Verdi" in h.text for h in hits)
    super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v1['id']}/restore")
    hits = _ask([t["id"]], "on call contact")
    assert hits and all("Mario Rossi" in h.text for h in hits)


def test_pending_version_only_in_test_question(super_admin):
    t = _tenant(super_admin, "Alfa")
    super_admin.patch(f"/api/tenants/{t['id']}", json={"settings": {"require_approval": True}})
    v = _upload(super_admin, t["id"], "Runbook.docx", _docx("Firewall maintenance window is Tuesday night"))
    run_jobs(super_admin)
    assert _ask([t["id"]], "firewall maintenance window") == []
    r = super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/search", json={"question": "firewall maintenance window"})
    assert r.status_code == 200 and "Tuesday" in r.json()[0]["text"]
    super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/approve")
    assert _ask([t["id"]], "firewall maintenance window")


def test_stale_index_flag_cannot_leak_inactive_version(super_admin):
    t = _tenant(super_admin, "Alfa")
    v1 = _upload(super_admin, t["id"], "Contacts.docx", _docx("Old contact is Mario Rossi"))
    run_jobs(super_admin)
    _upload(super_admin, t["id"], "Contacts.docx", _docx("New contact is Anna Verdi"))
    run_jobs(super_admin)
    # Simulate an index out of sync: v1 wrongly flagged active in Qdrant.
    vector_index.client().set_payload(vector_index.collection_name(t["id"]), payload={"active": True},
                                      points=models.Filter(must=[models.FieldCondition(key="version_id", match=models.MatchValue(value=v1["id"]))]))
    hits = _ask([t["id"]], "contact Mario Rossi")
    assert all(h.version_id != uuid.UUID(v1["id"]) for h in hits)


def test_customer_and_general_search_with_isolation(super_admin):
    alfa, beta, g = _tenant(super_admin, "Alfa"), _tenant(super_admin, "Beta"), _general(super_admin)
    _upload(super_admin, alfa["id"], "A.docx", _docx("Alfa escalation goes to the Alfa duty manager"))
    _upload(super_admin, beta["id"], "B.docx", _docx("Beta escalation goes to the Beta duty manager"))
    _upload(super_admin, g["id"], "G.docx", _docx("General escalation playbook for every duty manager"))
    approve_general(super_admin)
    hits = _ask([alfa["id"], g["id"]], "escalation duty manager")
    names = {h.tenant_name for h in hits}
    assert names == {"Alfa", "General Knowledge Base"}
    assert any(h.is_general for h in hits)
    assert all("Beta" not in h.text for h in hits)


def test_test_question_respects_tenant_scope(super_admin):
    alfa, beta = _tenant(super_admin, "Alfa"), _tenant(super_admin, "Beta")
    bv = _upload(super_admin, beta["id"], "B.docx", _docx("Beta secret procedure"))
    run_jobs(super_admin)
    r = super_admin.post("/api/invitations", json={"email": "ta@example.com", "full_name": "TA", "role": "tenant_admin", "tenant_ids": [alfa["id"]]})
    new_client(super_admin.app).post(f"/api/invitations/accept/{r.json()['invite_url'].rsplit('/', 1)[1]}", json={"password": PASSWORD})
    ta = new_client(super_admin.app)
    login(ta, "ta@example.com")
    assert ta.post(f"/api/tenants/{alfa['id']}/documents/versions/{bv['id']}/search", json={"question": "secret"}).status_code == 404
    assert ta.post(f"/api/tenants/{beta['id']}/documents/versions/{bv['id']}/search", json={"question": "secret"}).status_code == 404


# --- Failures and maintenance ---------------------------------------------------------

def test_embedding_failure_fails_version_and_keeps_active(super_admin):
    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "Contacts.docx", _docx("On call contact is Mario Rossi"))
    run_jobs(super_admin)

    def down(texts):
        raise embeddings.EmbeddingError("Embedding service not reachable")

    embeddings.set_embedder(down)
    v2 = _upload(super_admin, t["id"], "Contacts.docx", _docx("On call contact is Anna Verdi"))
    run_jobs(super_admin)
    v2 = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v2['id']}").json()
    assert v2["status"] == "failed" and v2["error"].startswith("Indexing failed")
    assert all(p.payload["version_id"] != v2["id"] for p in _points(t["id"]))
    embeddings.set_embedder(fake_embeddings.embed)
    assert all("Mario Rossi" in h.text for h in _ask([t["id"]], "on call contact"))
    # Retry once the service is back.
    super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v2['id']}/retry")
    run_jobs(super_admin)
    assert all("Anna Verdi" in h.text for h in _ask([t["id"]], "on call contact"))


def test_model_change_requires_reindex(super_admin):
    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure about phishing"))
    run_jobs(super_admin)
    cfg = super_admin.put("/api/platform/embedding", json={"model": "other-model"}).json()
    assert cfg["reindex_needed"] is True
    v = _upload(super_admin, t["id"], "B.docx", _docx("Second document"))
    run_jobs(super_admin)
    v = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v['id']}").json()
    assert v["status"] == "failed" and "Reindex" in v["error"]
    assert super_admin.post("/api/platform/embedding/reindex").status_code == 202
    run_jobs(super_admin)
    state = super_admin.get("/api/platform/embedding").json()
    assert state["reindex"]["status"] == "done" and state["reindex_needed"] is False
    assert _ask([t["id"]], "phishing procedure")


def test_delete_document_and_tenant_clean_index(super_admin):
    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure"))
    _upload(super_admin, t["id"], "B.docx", _docx("Beta procedure"))
    run_jobs(super_admin)
    doc_a = next(d for d in super_admin.get(f"/api/tenants/{t['id']}/documents").json() if d["name"] == "A.docx")
    super_admin.delete(f"/api/tenants/{t['id']}/documents/{doc_a['id']}")
    assert {p.payload["document_id"] for p in _points(t["id"])} == {
        next(d for d in super_admin.get(f"/api/tenants/{t['id']}/documents").json())["id"]}
    super_admin.request("DELETE", f"/api/tenants/{t['id']}", json={"confirm_name": "Alfa"})
    assert not vector_index.client().collection_exists(vector_index.collection_name(t["id"]))


def test_reject_keeps_index_on_active(super_admin):
    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "C.docx", _docx("Contact Mario Rossi"))
    run_jobs(super_admin)
    super_admin.patch(f"/api/tenants/{t['id']}", json={"settings": {"require_approval": True}})
    v2 = _upload(super_admin, t["id"], "C.docx", _docx("Contact Anna Verdi"))
    run_jobs(super_admin)
    super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v2['id']}/reject")
    assert all("Mario Rossi" in h.text for h in _ask([t["id"]], "contact"))


# --- Platform endpoints ------------------------------------------------------------------

def test_embedding_settings_and_status(super_admin):
    r = super_admin.put("/api/platform/embedding", json={"url": "http://tei.local/v1", "model": "BAAI/bge-m3", "api_key": "k"})
    assert r.status_code == 200 and r.json()["api_key_set"] is True and "k" not in str(r.json().get("url"))
    assert super_admin.put("/api/platform/embedding", json={"url": "ftp://x"}).status_code == 422
    assert super_admin.post("/api/platform/embedding/test").json() == {"ok": True, "dimensions": fake_embeddings.DIM, "model": "BAAI/bge-m3"}
    names = {s["name"]: s["state"] for s in super_admin.get("/api/platform/status").json()["services"]}
    assert names["Qdrant (vector index)"] == "ok" and names["Embeddings"] == "ok"


# --- HTTP embedding client -----------------------------------------------------------------

def test_http_client_openai_format(monkeypatch):
    embeddings.set_embedder(None)
    seen = {}

    class Recorder(TestClient):
        def post(self, url, **kw):
            seen["url"], seen["json"], seen["headers"] = url, kw["json"], kw.get("headers")
            return super().post(url, **kw)

    monkeypatch.setattr(embeddings.httpx, "Client", lambda timeout: Recorder(fake_embeddings.app))
    cfg = {"url": "http://embeddings/v1", "model": "BAAI/bge-m3", "api_key": "secret"}
    vecs = embeddings.embed(cfg, [f"text {i}" for i in range(70)])  # 3 batches of 32
    assert len(vecs) == 70 and len(vecs[0]) == fake_embeddings.DIM
    assert seen["url"] == "http://embeddings/v1/embeddings" and seen["json"]["model"] == "BAAI/bge-m3"
    assert seen["headers"] == {"Authorization": "Bearer secret"}


def test_http_client_errors(monkeypatch):
    embeddings.set_embedder(None)
    real_client = httpx.Client  # embeddings.httpx is the httpx module: keep the original before patching

    def refused(req):
        raise httpx.ConnectError("refused", request=req)

    monkeypatch.setattr(embeddings.httpx, "Client", lambda timeout: real_client(transport=httpx.MockTransport(refused), timeout=timeout))
    with pytest.raises(embeddings.EmbeddingError, match="not reachable"):
        embeddings.embed({"url": "http://down/v1", "model": "m", "api_key": None}, ["x"])

    monkeypatch.setattr(embeddings.httpx, "Client", lambda timeout: real_client(transport=httpx.MockTransport(lambda req: httpx.Response(500, text="boom"))))
    with pytest.raises(embeddings.EmbeddingError, match="answered 500"):
        embeddings.embed({"url": "http://x/v1", "model": "m", "api_key": None}, ["x"])


def test_reprocess_reads_documents_again_and_keeps_them_in_use(super_admin):
    from sqlalchemy import select

    from app.models import Chunk

    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure about phishing"))
    run_jobs(super_admin)
    before = {c.id for c in _db().scalars(select(Chunk))}
    assert super_admin.post("/api/platform/embedding/reprocess").status_code == 202
    assert super_admin.post("/api/platform/embedding/reindex").status_code == 409  # one job at a time
    run_jobs(super_admin)
    state = super_admin.get("/api/platform/embedding").json()["reprocess"]
    assert state["status"] == "done" and state["total"] == 1 and state["error"] is None
    after = {c.id for c in _db().scalars(select(Chunk))}
    assert after and not (after & before)
    assert {p.payload["chunk_id"] for p in _points(t["id"])} == {str(c) for c in after}
    assert _ask([t["id"]], "phishing procedure")
    doc = super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]
    assert doc["active"]["status"] == "ready"


def test_answers_pause_while_the_index_is_rebuilt(super_admin):
    from app.models import PlatformSetting
    from app.services import embeddings

    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure about phishing"))
    run_jobs(super_admin)
    db = _db()
    from app.models.base import utcnow

    db.add(PlatformSetting(key="reindex", value={"status": "running", "done": 3, "total": 9, "blocking": True,
                                                 "updated_at": utcnow().isoformat()}))
    db.commit()
    with pytest.raises(embeddings.EmbeddingError, match="being rebuilt"):
        _ask([t["id"]], "phishing procedure")
    db.get(PlatformSetting, "reindex").value = {"status": "running", "blocking": True, "updated_at": "2020-01-01T00:00:00+00:00"}
    db.commit()  # a worker killed mid-run: no longer "being rebuilt", but the index is still incomplete
    with pytest.raises(embeddings.EmbeddingError, match="Reindex again"):
        _ask([t["id"]], "phishing procedure")
    assert super_admin.post("/api/platform/embedding/reindex").status_code == 202  # a stale run does not block a new one
    super_admin.queued.clear()
    assert _db().get(PlatformSetting, "reindex").value["blocking"] is True  # still incomplete until a run succeeds
    db = _db()
    db.get(PlatformSetting, "reindex").value = {"status": "failed", "error": "x", "blocking": True}
    db.commit()
    with pytest.raises(embeddings.EmbeddingError, match="Reindex again"):
        _ask([t["id"]], "phishing procedure")
    db = _db()
    db.get(PlatformSetting, "reindex").value = {"status": "failed", "error": "Redis down"}  # nothing was cleared
    db.commit()
    assert _ask([t["id"]], "phishing procedure")
