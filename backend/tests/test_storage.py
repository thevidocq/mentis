"""Long-term storage: deletion order, the storage sweep, old-version retention."""

import uuid

from sqlalchemy import select

from app.core import db as db_module
from app.models import Chunk, DocumentVersion, VersionPage
from app.services import storage, vector_index
from tests import samples
from tests.conftest import run_jobs
from tests.test_documents import _docx_variant, _tenant, _upload


def _db():
    return next(db_module.get_db())


def _docx(n: int) -> bytes:
    import io

    import docx

    d = docx.Document()
    d.add_heading(f"Runbook revision {n}", level=1)
    d.add_paragraph(f"Escalation contact number {n}: call the on-call engineer.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _keys(prefix=""):
    return [k for k in storage.get_storage().objects if k.startswith(prefix)]


def test_delete_document_survives_storage_failure_and_sweep_cleans_up(super_admin, monkeypatch):
    t = _tenant(super_admin)
    _upload(super_admin, t["id"], "Scan.pdf", samples.scanned_pdf())
    run_jobs(super_admin)
    doc = super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]
    assert _keys(f"tenants/{t['id']}/") and vector_index.version_ids(t["id"])

    def down(prefix):
        raise OSError("MinIO down")
    monkeypatch.setattr(storage.get_storage(), "delete_prefix", down)
    assert super_admin.delete(f"/api/tenants/{t['id']}/documents/{doc['id']}").status_code == 204
    assert super_admin.get(f"/api/tenants/{t['id']}/documents").json() == []
    assert _keys(f"tenants/{t['id']}/")  # files left behind
    monkeypatch.undo()

    r = super_admin.post("/api/platform/retention/purge").json()
    assert r["orphan_files"] == 1 and _keys(f"tenants/{t['id']}/") == []
    assert vector_index.version_ids(t["id"]) == set()


def test_sweep_removes_only_leftovers(super_admin):
    t = _tenant(super_admin)
    _upload(super_admin, t["id"], "Runbook.docx", samples.docx())
    run_jobs(super_admin)
    store = storage.get_storage()
    ghost_version, ghost_tenant = uuid.uuid4(), uuid.uuid4()
    store.put(f"tenants/{t['id']}/versions/{ghost_version}/original.pdf", b"x", "application/pdf")
    store.put(f"tenants/{ghost_tenant}/versions/{uuid.uuid4()}/original.pdf", b"x", "application/pdf")
    vector_index.upsert_chunks(t["id"], uuid.uuid4(), ghost_version, False, [(uuid.uuid4(), [0.1] * len(_any_vector(t["id"])))])
    kept = set(_keys(f"tenants/{t['id']}/"))

    r = super_admin.post("/api/platform/retention/purge").json()
    assert r["orphan_files"] == 2 and r["orphan_vectors"] == 1
    assert _keys(f"tenants/{ghost_tenant}/") == []
    assert set(_keys(f"tenants/{t['id']}/")) == {k for k in kept if str(ghost_version) not in k}
    assert str(ghost_version) not in vector_index.version_ids(t["id"]) and vector_index.version_ids(t["id"])
    # The documents still answer.
    v = super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]["active"]
    assert super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/search", json={"question": "procedure"}).status_code == 200


def _any_vector(tenant_id):
    c = vector_index.client()
    p, _ = c.scroll(vector_index.collection_name(tenant_id), limit=1, with_vectors=True)
    return p[0].vector


def test_old_versions_retention(super_admin):
    t = _tenant(super_admin)
    for n in range(1, 5):
        _upload(super_admin, t["id"], "Runbook.docx", _docx(n))
        run_jobs(super_admin)
    db = _db()
    vs = {v.version: v.id for v in db.scalars(select(DocumentVersion))}
    db.close()
    assert sorted(vs) == [1, 2, 3, 4]
    # Default: keep everything.
    assert super_admin.post("/api/platform/retention/purge").json()["versions"] == 0
    assert super_admin.put("/api/platform/retention", json={"chats_days": 365, "logs_days": 365, "versions_keep": 1}).status_code == 200
    assert super_admin.put("/api/platform/retention", json={"chats_days": 365, "logs_days": 365, "versions_keep": 101}).status_code == 422
    r = super_admin.post("/api/platform/retention/purge").json()
    assert r["versions"] == 2  # v4 in use, v3 kept, v2 and v1 deleted
    db = _db()
    left = {v.version for v in db.scalars(select(DocumentVersion))}
    assert left == {3, 4}
    for gone in (vs[1], vs[2]):
        assert db.scalar(select(VersionPage.id).where(VersionPage.version_id == gone)) is None
        assert db.scalar(select(Chunk.id).where(Chunk.version_id == gone)) is None
        assert _keys(f"tenants/{t['id']}/versions/{gone}/") == []
        assert str(gone) not in vector_index.version_ids(t["id"])
    db.close()
    doc = super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]
    assert doc["active"]["version"] == 4 and doc["versions"] == 2


def test_pending_and_latest_versions_are_kept(super_admin):
    t = _tenant(super_admin)
    _upload(super_admin, t["id"], "Runbook.docx", _docx(1))
    run_jobs(super_admin)
    _upload(super_admin, t["id"], "Runbook.docx", _docx_variant())
    run_jobs(super_admin)
    v1 = next(v for v in super_admin.get(f"/api/tenants/{t['id']}/documents/{super_admin.get(f'/api/tenants/{t["id"]}/documents').json()[0]['id']}").json()["versions"] if v["version"] == 1)
    assert super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v1['id']}/restore").status_code == 200
    super_admin.put("/api/platform/retention", json={"chats_days": 365, "logs_days": 365, "versions_keep": 1})
    assert super_admin.post("/api/platform/retention/purge").json()["versions"] == 0  # v1 in use, v2 the latest


def test_sweep_never_takes_an_upload_in_progress_for_a_leftover(super_admin, monkeypatch):
    """An upload that commits its row and writes its files while the sweep runs keeps them."""
    t = _tenant(super_admin)
    store = storage.get_storage()
    real = store.list_dirs
    done = []

    def list_dirs(prefix):
        out = real(prefix)
        if prefix == "tenants/" and not done:  # the sweep has started listing: an upload lands now
            done.append(1)
            _upload(super_admin, t["id"], "Runbook.docx", samples.docx())
            out = real(prefix)
        return out
    monkeypatch.setattr(store, "list_dirs", list_dirs)
    r = super_admin.post("/api/platform/retention/purge").json()
    assert done and r["orphan_files"] == 0
    monkeypatch.undo()
    run_jobs(super_admin)
    assert super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]["active"]
