"""Downloads for use elsewhere: one version as Markdown or JSON, every document in use as a ZIP."""

import io
import json
import zipfile

from tests.conftest import run_jobs
from tests.test_indexing import _docx, _tenant, _upload


def _ready(c, tenant_id, name, text):
    v = _upload(c, tenant_id, name, _docx(text))
    run_jobs(c)
    return v


def test_version_as_markdown_and_json(super_admin):
    alfa = _tenant(super_admin, "Alfa")
    v = _ready(super_admin, alfa["id"], "Escalation.docx", "Escalate brute force attacks to Mario Rossi phone 111")
    base = f"/api/tenants/{alfa['id']}/documents/versions/{v['id']}/export"
    md = super_admin.get(base, params={"format": "md"})
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert 'filename="Escalation v1.md"' in md.headers["content-disposition"]
    assert md.text.startswith("# Escalation.docx") and "- Customer: Alfa" in md.text and "Mario Rossi" in md.text and "\n## " in md.text
    data = super_admin.get(base, params={"format": "json"}).json()
    assert data["format"] == "mentis-document/1" and data["customer"] == "Alfa" and data["document"]["version"] == 1
    assert data["pages"] and any("Mario Rossi" in p["text"] for p in data["pages"])
    assert data["passages"] and data["passages"][0]["page_label"]
    assert super_admin.get(base, params={"format": "exe"}).status_code == 422


def test_unread_version_has_only_the_original(super_admin):
    alfa = _tenant(super_admin, "Alfa")
    v = _upload(super_admin, alfa["id"], "Queued.docx", _docx("not processed yet"))  # no run_jobs: still queued
    r = super_admin.get(f"/api/tenants/{alfa['id']}/documents/versions/{v['id']}/export", params={"format": "md"})
    assert r.status_code == 409


def test_zip_of_documents_in_use(super_admin):
    alfa = _tenant(super_admin, "Alfa")
    _ready(super_admin, alfa["id"], "Escalation.docx", "Escalate brute force attacks to Mario Rossi")
    _ready(super_admin, alfa["id"], "Phishing.docx", "Phishing triage checklist")
    _upload(super_admin, alfa["id"], "Pending.docx", _docx("queued, not in use"))
    for fmt, ext in (("original", "docx"), ("md", "md"), ("json", "json")):
        r = super_admin.get(f"/api/tenants/{alfa['id']}/documents/export", params={"format": fmt})
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/zip" and ".zip" in r.headers["content-disposition"]
        z = zipfile.ZipFile(io.BytesIO(r.content))
        names = sorted(z.namelist())
        assert names == sorted([f"Escalation.{ext}", f"Phishing.{ext}", "manifest.json"]), names
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["customer"] == "Alfa" and manifest["content"] == fmt and manifest["not_included"] == 1
    md = zipfile.ZipFile(io.BytesIO(super_admin.get(f"/api/tenants/{alfa['id']}/documents/export", params={"format": "md"}).content))
    assert "Mario Rossi" in md.read("Escalation.md").decode()


def test_zip_limits_and_empty(super_admin, monkeypatch):
    from app.core.config import get_settings

    alfa = _tenant(super_admin, "Alfa")
    assert super_admin.get(f"/api/tenants/{alfa['id']}/documents/export", params={"format": "md"}).status_code == 409
    _ready(super_admin, alfa["id"], "Escalation.docx", "Escalate brute force attacks")
    monkeypatch.setattr(get_settings(), "export_max_mb", 0)
    r = super_admin.get(f"/api/tenants/{alfa['id']}/documents/export", params={"format": "original"})
    assert r.status_code == 413 and "one by one" in r.json()["detail"]
    # Markdown and JSON have the same cap (the ZIP is built in the api's /tmp).
    assert super_admin.get(f"/api/tenants/{alfa['id']}/documents/export", params={"format": "json"}).status_code == 413
    monkeypatch.setattr(get_settings(), "export_max_mb", 300)
    assert super_admin.get(f"/api/tenants/{alfa['id']}/documents/export", params={"format": "json"}).status_code == 200


def test_export_is_audited_and_only_for_the_tenant_admin(super_admin):
    alfa, beta = _tenant(super_admin, "Alfa"), _tenant(super_admin, "Beta")
    v = _ready(super_admin, alfa["id"], "Escalation.docx", "Escalate brute force attacks")
    # Alfa's version under Beta's id: not found.
    assert super_admin.get(f"/api/tenants/{beta['id']}/documents/versions/{v['id']}/export", params={"format": "md"}).status_code == 404
    assert super_admin.direct("GET", f"/api/tenants/{alfa['id']}/documents/export", params={"format": "md"}).status_code == 403
    super_admin.get(f"/api/tenants/{alfa['id']}/documents/export", params={"format": "md"})
    logs = super_admin.get("/api/logs", params={"action": "documents.exported"}).json()
    assert logs["total"] == 1 and logs["items"][0]["detail"]["format"] == "md"
