"""API answers carry tenant data: the browser must not keep them (shared PCs, back button after sign-out)."""

from tests import samples
from tests.conftest import run_jobs
from tests.test_tenants_users import _create_tenant


def test_api_responses_are_not_stored(super_admin):
    tenant = _create_tenant(super_admin)
    for r in (
        super_admin.get("/api/auth/me"),
        super_admin.get("/api/tenants"),
        super_admin.get(f"/api/tenants/{tenant['id']}/documents"),
        super_admin.get("/api/does-not-exist"),
    ):
        assert r.headers["cache-control"] == "no-store", r.request.url


def test_page_images_and_originals_are_not_stored(super_admin):
    tenant = _create_tenant(super_admin)
    files = {"file": ("Scan.pdf", samples.scanned_pdf(), "application/octet-stream")}
    vid = super_admin.post(f"/api/tenants/{tenant['id']}/documents", files=files).json()["id"]
    run_jobs(super_admin)
    base = f"/api/tenants/{tenant['id']}/documents/versions/{vid}"
    for r in (super_admin.get(f"{base}/pages/1/image"), super_admin.get(f"{base}/original")):
        assert r.status_code == 200, r.request.url
        assert r.headers["cache-control"] == "no-store", r.request.url


def test_errors_and_anonymous_answers_are_not_stored(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.headers["cache-control"] == "no-store"
    # Rejected by the CSRF guard (another middleware) before any route runs.
    r = client.post("/api/auth/logout", headers={"X-Mentis-Request": ""})
    assert r.status_code == 403
    assert r.headers["cache-control"] == "no-store"
