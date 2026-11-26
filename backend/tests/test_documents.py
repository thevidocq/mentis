import uuid

import pytest
from sqlalchemy import select

from app.core import db as db_module
from app.models import AuditEvent, Chunk, DocumentVersion, VersionPage
from app.services.uploads import UploadError, check_upload
from tests import samples
from tests.conftest import PASSWORD, login, new_client, run_jobs


def _db():
    return next(db_module.get_db())


def _tenant(c, name="Cliente Alfa"):
    return c.post("/api/tenants", json={"name": name}).json()


def _general(c):
    return next(t for t in c.get("/api/tenants").json() if t["is_global"])


def _upload(c, tenant_id, filename, data, note=None):
    files = {"file": (filename, data, "application/octet-stream")}
    return c.post(f"/api/tenants/{tenant_id}/documents", files=files, data={"note": note} if note else None)


def _tenant_admin(super_admin, tenant_id, email="ta@example.com"):
    r = super_admin.post("/api/invitations", json={"email": email, "full_name": "TA", "role": "tenant_admin", "tenant_ids": [tenant_id]})
    token = r.json()["invite_url"].rsplit("/", 1)[1]
    anon = new_client(super_admin.app)
    anon.post(f"/api/invitations/accept/{token}", json={"password": PASSWORD})
    c = new_client(super_admin.app)
    login(c, email)
    c.queued = super_admin.queued
    return c


# --- Upload validation (unit) -----------------------------------------------------

@pytest.mark.parametrize("name,data,reason", [
    ("a.exe", b"MZ....", "Only PDF"),
    ("a.docm", b"PK..", "macro"),
    ("a.doc", b"\xd0\xcf\x11\xe0", "old Word"),
    ("a.pdf", b"", "empty"),
    ("a.pdf", b"<html>not a pdf</html>", "not a valid PDF"),
    ("a.docx", b"%PDF-1.4 fake", "not a valid .docx"),
    ("a.xlsx", samples.docx(), "not a valid .xlsx"),           # a Word file renamed .xlsx
    ("a.docx", samples.macro_docx(), "macros"),
    ("a.docx", b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100, "Encrypted"),
])
def test_upload_refused(name, data, reason):
    with pytest.raises(UploadError, match=reason):
        check_upload(name, data)


def test_zip_bomb_refused(monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.get_settings(), "max_unzipped_mb", 5)
    with pytest.raises(UploadError, match="expands"):
        check_upload("bomb.xlsx", samples.zip_bomb_xlsx(10))


def test_filename_sanitized():
    checked = check_upload("../../etc/Procedure\x00_SOC.pdf", samples.native_pdf())
    assert checked.filename == "Procedure_SOC.pdf"
    assert checked.file_type == "pdf" and len(checked.sha256) == 64


# --- Pipeline -----------------------------------------------------------------------

@pytest.mark.parametrize("filename,builder,expect", [
    ("Procedure_SOC.pdf", samples.native_pdf, "escalate to the on-call L2"),
    ("Scan.pdf", samples.scanned_pdf, "Mario Rossi"),
    ("Runbook.docx", samples.docx, "| Network lead | Anna Verdi |"),
    ("Playbook.pptx", samples.pptx, "Call the customer on-call"),
    ("Escalation_Matrix.xlsx", samples.xlsx, "| L2 | Mario Rossi | 085 123 4567 |"),
])
def test_ingest_each_format(super_admin, filename, builder, expect):
    t = _tenant(super_admin)
    r = _upload(super_admin, t["id"], filename, builder())
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "queued"
    run_jobs(super_admin)
    v = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{r.json()['id']}").json()
    assert v["status"] == "ready", v
    assert v["is_active"] is True and v["approval"] == "not_required"
    pages = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/pages").json()
    assert expect in "\n".join(p["text"] for p in pages)
    assert _db().scalars(select(Chunk).where(Chunk.version_id == uuid.UUID(v["id"]))).first() is not None


def test_scanned_pdf_marked_as_ocr_with_image(super_admin):
    t = _tenant(super_admin)
    vid = _upload(super_admin, t["id"], "Scan.pdf", samples.scanned_pdf()).json()["id"]
    run_jobs(super_admin)
    pages = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{vid}/pages").json()
    assert pages[0]["method"] == "ocr" and pages[0]["ocr_confidence"] > 0.6 and pages[0]["has_image"]
    img = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{vid}/pages/1/image")
    assert img.status_code == 200 and img.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_unreadable_pdf_fails_without_touching_active(super_admin):
    t = _tenant(super_admin)
    good = _upload(super_admin, t["id"], "P.pdf", samples.native_pdf()).json()
    run_jobs(super_admin)
    broken = b"%PDF-1.4\n" + b"garbage" * 50
    bad = _upload(super_admin, t["id"], "P.pdf", broken).json()
    run_jobs(super_admin)
    detail = super_admin.get(f"/api/tenants/{t['id']}/documents/{_doc_id(super_admin, t['id'])}").json()
    by_version = {v["version"]: v for v in detail["versions"]}
    assert by_version[2]["status"] == "failed" and by_version[2]["error"]
    assert by_version[1]["is_active"] is True and by_version[1]["id"] == good["id"]
    assert bad["id"] == by_version[2]["id"]


def _doc_id(c, tenant_id):
    return c.get(f"/api/tenants/{tenant_id}/documents").json()[0]["id"]


# --- Versions ------------------------------------------------------------------------

def test_new_version_replaces_active_and_restore(super_admin):
    t = _tenant(super_admin)
    _upload(super_admin, t["id"], "Runbook.docx", samples.docx())
    run_jobs(super_admin)
    _upload(super_admin, t["id"], "runbook.DOCX", _docx_variant())
    run_jobs(super_admin)
    docs = super_admin.get(f"/api/tenants/{t['id']}/documents").json()
    assert len(docs) == 1 and docs[0]["versions"] == 2 and docs[0]["active"]["version"] == 2
    v1 = next(v for v in super_admin.get(f"/api/tenants/{t['id']}/documents/{docs[0]['id']}").json()["versions"] if v["version"] == 1)
    assert super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v1['id']}/restore").status_code == 200
    assert super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]["active"]["version"] == 1


def _docx_variant() -> bytes:
    import io

    import docx

    d = docx.Document()
    d.add_heading("Firewall runbook v2", level=1)
    d.add_paragraph("Maintenance windows moved to Wednesdays.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_identical_file_refused(super_admin):
    t = _tenant(super_admin)
    _upload(super_admin, t["id"], "Runbook.docx", samples.docx())
    run_jobs(super_admin)
    assert _upload(super_admin, t["id"], "Runbook.docx", samples.docx()).status_code == 409


def test_approval_flow(super_admin):
    t = _tenant(super_admin)
    super_admin.patch(f"/api/tenants/{t['id']}", json={"settings": {"require_approval": True}})
    v = _upload(super_admin, t["id"], "Runbook.docx", samples.docx()).json()
    run_jobs(super_admin)
    v = super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{v['id']}").json()
    assert v["approval"] == "pending" and v["is_active"] is False
    assert super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/restore").status_code == 409
    r = super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/approve")
    assert r.status_code == 200 and r.json()["is_active"] is True
    # A rejected new version leaves the approved one active.
    v2 = _upload(super_admin, t["id"], "Runbook.docx", _docx_variant()).json()
    run_jobs(super_admin)
    assert super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v2['id']}/reject").json()["is_active"] is False
    assert super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]["active"]["id"] == v["id"]


def test_retry_failed(super_admin):
    t = _tenant(super_admin)
    v = _upload(super_admin, t["id"], "P.pdf", b"%PDF-1.4\n" + b"x" * 100).json()
    run_jobs(super_admin)
    r = super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/retry")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert super_admin.post(f"/api/tenants/{t['id']}/documents/versions/{v['id']}/retry").status_code == 409


# --- Isolation -----------------------------------------------------------------------

def test_tenant_admin_cannot_reach_other_tenant(super_admin):
    alfa, beta = _tenant(super_admin, "Alfa"), _tenant(super_admin, "Beta")
    beta_doc = _upload(super_admin, beta["id"], "Secret.docx", samples.docx()).json()
    run_jobs(super_admin)
    ta = _tenant_admin(super_admin, alfa["id"])
    base_beta = f"/api/tenants/{beta['id']}/documents"
    assert ta.get(base_beta).status_code == 404
    assert _upload(ta, beta["id"], "x.pdf", samples.native_pdf()).status_code == 404
    # Beta's version id used through Alfa's path: not found either.
    base_alfa = f"/api/tenants/{alfa['id']}/documents"
    assert ta.get(f"{base_alfa}/versions/{beta_doc['id']}").status_code == 404
    assert ta.get(f"{base_alfa}/versions/{beta_doc['id']}/pages").status_code == 404
    assert ta.get(f"{base_alfa}/versions/{beta_doc['id']}/original").status_code == 404
    assert ta.post(f"{base_alfa}/versions/{beta_doc['id']}/restore").status_code == 404
    # Own tenant works.
    assert _upload(ta, alfa["id"], "Mine.docx", samples.docx()).status_code == 201
    assert len(ta.get(base_alfa).json()) == 1


def test_analyst_has_no_document_access(super_admin):
    t = _tenant(super_admin)
    r = super_admin.post("/api/invitations", json={"email": "an@example.com", "full_name": "An", "role": "analyst", "all_tenants": True})
    token = r.json()["invite_url"].rsplit("/", 1)[1]
    new_client(super_admin.app).post(f"/api/invitations/accept/{token}", json={"password": PASSWORD})
    an = new_client(super_admin.app)
    login(an, "an@example.com")
    assert an.get(f"/api/tenants/{t['id']}/documents").status_code == 403


def test_general_documents_by_super_admin(super_admin):
    g = _general(super_admin)
    assert _upload(super_admin, g["id"], "Playbook.pptx", samples.pptx()).status_code == 201


# --- Deletion ------------------------------------------------------------------------

def test_delete_document_removes_files_and_rows(super_admin):
    t = _tenant(super_admin)
    _upload(super_admin, t["id"], "Scan.pdf", samples.scanned_pdf())
    run_jobs(super_admin)
    assert super_admin.storage.objects
    doc_id = _doc_id(super_admin, t["id"])
    assert super_admin.delete(f"/api/tenants/{t['id']}/documents/{doc_id}").status_code == 204
    assert not super_admin.storage.objects
    db = _db()
    assert db.scalars(select(DocumentVersion)).first() is None and db.scalars(select(VersionPage)).first() is None


def test_delete_tenant_removes_documents(super_admin):
    t = _tenant(super_admin)
    _upload(super_admin, t["id"], "Runbook.docx", samples.docx())
    run_jobs(super_admin)
    r = super_admin.request("DELETE", f"/api/tenants/{t['id']}", json={"confirm_name": t["name"]})
    assert r.status_code == 204
    assert not super_admin.storage.objects
    assert _db().scalars(select(Chunk)).first() is None


def test_upload_events_logged(super_admin):
    t = _tenant(super_admin)
    _upload(super_admin, t["id"], "bad.exe", b"MZ")
    _upload(super_admin, t["id"], "Runbook.docx", samples.docx())
    run_jobs(super_admin)
    actions = {e.action for e in _db().scalars(select(AuditEvent))}
    assert {"document.upload_refused", "document.uploaded", "document.processed"} <= actions


def test_rename_keeps_extension_and_name_unique(super_admin):
    t = _tenant(super_admin)
    _upload(super_admin, t["id"], "Runbook.docx", samples.docx())
    _upload(super_admin, t["id"], "Matrix.xlsx", samples.xlsx())
    run_jobs(super_admin)
    docs = {d["name"]: d["id"] for d in super_admin.get(f"/api/tenants/{t['id']}/documents").json()}
    base = f"/api/tenants/{t['id']}/documents/{docs['Runbook.docx']}"
    assert super_admin.patch(base, json={"name": "Runbook.pdf"}).status_code == 422
    assert super_admin.patch(base, json={"name": "matrix.XLSX"}).status_code == 422
    assert super_admin.patch(base, json={"name": "Firewall Runbook.docx"}).status_code == 200


def test_storage_failure_does_not_leave_a_version(super_admin, monkeypatch):
    t = _tenant(super_admin)

    def boom(*a, **k):
        raise ConnectionError("minio down")

    monkeypatch.setattr(super_admin.storage, "put", boom)
    assert _upload(super_admin, t["id"], "Runbook.docx", samples.docx()).status_code == 503
    assert _db().scalars(select(DocumentVersion)).first() is None
    from app.models import Document
    assert _db().scalars(select(Document)).first() is None
    assert super_admin.queued == []


def test_stuck_versions_are_recovered(super_admin, monkeypatch):
    from datetime import timedelta

    from app.core import db as db_module
    from app.models import DocumentVersion
    from app.models.base import utcnow
    from app.services import jobs, recovery

    t = super_admin.post("/api/tenants", json={"name": "Alfa"}).json()
    a = _upload(super_admin, t["id"], "A.docx", samples.docx()).json()
    b = _upload(super_admin, t["id"], "B.docx", samples.docx()).json()
    super_admin.queued.clear()
    db = next(db_module.get_db())
    va, vb = db.get(DocumentVersion, uuid.UUID(a["id"])), db.get(DocumentVersion, uuid.UUID(b["id"]))
    va.status, va.status_at = "processing", utcnow() - timedelta(hours=3)  # the worker died mid-job
    vb.status, vb.status_at = "queued", utcnow() - timedelta(hours=2)      # Redis lost the job
    db.commit()
    monkeypatch.setattr(jobs, "ingest_job_pending", lambda vid: False)
    assert recovery.recover_stuck_versions(next(db_module.get_db())) == {"failed": 1, "requeued": 1}
    assert super_admin.get(f"/api/tenants/{t['id']}/documents/versions/{a['id']}").json()["error"].startswith("Processing was interrupted")
    assert super_admin.queued == [("ingest", b["id"])]
    # Nothing left to do on a second pass.
    assert recovery.recover_stuck_versions(next(db_module.get_db())) == {"failed": 0, "requeued": 0}


def test_purge_removes_expired_sessions_and_old_invitations(super_admin):
    from datetime import timedelta

    from app.core import db as db_module
    from app.models import AuthSession, Invitation
    from app.models.base import utcnow

    super_admin.post("/api/invitations", json={"email": "old@example.com", "full_name": "Old", "role": "analyst"})
    db = next(db_module.get_db())
    for s in db.query(AuthSession):
        s.expires_at = utcnow() - timedelta(hours=1)
    for i in db.query(Invitation):
        i.expires_at = utcnow() - timedelta(days=8)
    db.commit()
    from app.services import retention

    retention.purge(db)
    db = next(db_module.get_db())
    assert db.query(AuthSession).count() == 0 and db.query(Invitation).count() == 0


def test_new_version_by_document_id_whatever_the_file_name(super_admin):
    t, other = _tenant(super_admin), _tenant(super_admin, "Cliente Beta")
    _upload(super_admin, t["id"], "Runbook.docx", samples.docx())
    run_jobs(super_admin)
    doc = super_admin.get(f"/api/tenants/{t['id']}/documents").json()[0]
    files = {"file": ("Runbook_2026_final.docx", _docx_variant(), "application/octet-stream")}
    r = super_admin.post(f"/api/tenants/{t['id']}/documents", files=files, data={"document_id": doc["id"]})
    assert r.status_code == 201, r.text
    run_jobs(super_admin)
    docs = super_admin.get(f"/api/tenants/{t['id']}/documents").json()
    assert len(docs) == 1 and docs[0]["name"] == "Runbook.docx" and docs[0]["versions"] == 2
    # Another file type, or a document of another customer: refused.
    pdf = {"file": ("Runbook.pdf", samples.native_pdf(), "application/octet-stream")}
    r = super_admin.post(f"/api/tenants/{t['id']}/documents", files=pdf, data={"document_id": doc["id"]})
    assert r.status_code == 422
    r = super_admin.post(f"/api/tenants/{other['id']}/documents", files=files, data={"document_id": doc["id"]})
    assert r.status_code == 404


def test_overview(super_admin):
    t = _tenant(super_admin)
    _upload(super_admin, t["id"], "Runbook.docx", samples.docx())
    _upload(super_admin, t["id"], "Scan.pdf", samples.scanned_pdf())
    run_jobs(super_admin)
    _upload(super_admin, t["id"], "Broken.pdf", b"%PDF-1.4 not really")
    run_jobs(super_admin)
    o = super_admin.get(f"/api/tenants/{t['id']}/documents/overview").json()
    assert o["documents"] == 3 and o["in_use"] == 2 and o["needs_attention"] == 1
    assert o["attention"][0]["document"] == "Broken.pdf" and o["attention"][0]["status"] == "failed"
    assert o["pages"] >= 2 and o["ocr_pages"] >= 1 and o["passages"] >= 2
    assert o["by_type"] == {"docx": 1, "pdf": 1} and o["embedding_model"]
    assert [r["document"] for r in o["recent"]][0] == "Broken.pdf" and o["recent"][0]["uploaded_by"]
    assert o["questions"] == {"answered": 0, "not_found": 0, "errors": 0}
    assert o["last_indexed"] and o["oldest_in_use"]
