"""Robustness of the document pipeline: queue outages, index errors, model changes, huge rows, deletes."""

import uuid

from app.core import db as db_module
from app.ingestion.chunking import MAX_CHARS, chunk_pages
from app.ingestion.types import ExtractedPage
from app.models import DocumentVersion, VersionStatus
from app.services import jobs, vector_index
from app.worker import tasks
from tests.conftest import run_jobs
from tests.test_chat import _analyst, _provider, fake_llm  # noqa: F401 - fixture
from tests.test_indexing import _docx, _points, _tenant, _upload


def test_upload_survives_a_queue_outage(super_admin, monkeypatch):
    t = _tenant(super_admin, "Alfa")

    def down(*_a, **_k):
        raise ConnectionError("redis down")

    monkeypatch.setattr(jobs, "enqueue_ingest", down)
    v = _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure"))
    assert v["status"] == "queued"  # the worker's recovery queues it again later


def test_reindex_without_documents_records_the_new_model(super_admin):
    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure"))
    run_jobs(super_admin)
    doc = super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]
    super_admin.delete(f"/api/tenants/{t['id']}/documents/{doc['id']}")
    super_admin.put("/api/platform/embedding", json={"model": "other-model"})
    assert super_admin.post("/api/platform/embedding/reindex").status_code == 202
    run_jobs(super_admin)
    assert super_admin.get("/api/platform/embedding").json()["reindex_needed"] is False
    v = _upload(super_admin, t["id"], "B.docx", _docx("Beta procedure"))
    run_jobs(super_admin)
    assert super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v['id']}").json()["status"] == "ready"


def test_index_errors_become_readable_answers(super_admin, fake_llm, monkeypatch):  # noqa: F811
    _provider(super_admin)
    t = _tenant(super_admin, "Alfa")
    v = _upload(super_admin, t["id"], "A.docx", _docx("Escalate brute force attacks to Mario Rossi"))
    run_jobs(super_admin)

    def broken(*_a, **_k):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(vector_index.client(), "query_points", broken)
    an = _analyst(super_admin)
    r = an.post("/api/chats", json={"tenant_id": t["id"], "message": "brute force escalation"})
    assert r.status_code == 201 and r.json()["answer"]["status"] == "error"
    assert "vector index" in r.json()["answer"]["content"]
    r = super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/search", json={"question": "brute force"})
    assert r.status_code == 503


def test_model_changed_without_reindex_answers_with_a_clear_error(super_admin, fake_llm):  # noqa: F811
    _provider(super_admin)
    t = _tenant(super_admin, "Alfa")
    _upload(super_admin, t["id"], "A.docx", _docx("Escalate brute force attacks to Mario Rossi"))
    run_jobs(super_admin)
    super_admin.put("/api/platform/embedding", json={"model": "other-model"})
    an = _analyst(super_admin)
    a = an.post("/api/chats", json={"tenant_id": t["id"], "message": "brute force escalation"}).json()["answer"]
    assert a["status"] == "error" and "Reindex" in a["content"]


def test_huge_table_row_is_split_with_its_header():
    row = "| " + ("very long cell text. " * 400) + " | x |"
    page = ExtractedPage(index=1, kind="sheet", label="Contacts", text="| Notes | Id |\n| --- | --- |\n" + row + "\n| short | y |",
                         method="text")
    chunks = chunk_pages([page])
    assert len(chunks) > 2 and all(len(c.text) <= MAX_CHARS for c in chunks)
    assert all(c.text.startswith("| Notes | Id |\n| --- | --- |") for c in chunks)
    assert chunks[-1].text.endswith("| short | y |")


def test_version_deleted_while_processing_leaves_no_points(super_admin, monkeypatch):
    t = _tenant(super_admin, "Alfa")
    v = _upload(super_admin, t["id"], "A.docx", _docx("Alfa procedure about phishing"))
    doc = super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]
    real_on_ready = tasks.versions.on_ready

    def delete_meanwhile(db, version):
        # Another request deletes the document after the points were written, before the commit.
        other = next(db_module.get_db())
        row = other.get(DocumentVersion, version.id)
        assert row is not None and row.status != VersionStatus.READY
        other.close()
        super_admin.delete(f"/api/tenants/{t['id']}/documents/{doc['id']}")
        real_on_ready(db, version)

    monkeypatch.setattr(tasks.versions, "on_ready", delete_meanwhile)
    run_jobs(super_admin)
    assert not [p for p in _points(t["id"]) if p.payload["version_id"] == v["id"]]
    assert next(db_module.get_db()).get(DocumentVersion, uuid.UUID(v["id"])) is None
