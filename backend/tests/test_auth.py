import pyotp
from fastapi import Depends
from sqlalchemy import select

from app.api.deps import require_roles
from app.core import db as db_module
from app.models import AuditEvent, Role, Tenant, User
from tests.conftest import PASSWORD


def _login_and_enroll(client, email="admin@example.com", password=PASSWORD):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    assert r.json()["next_step"] == "mfa_enrollment"
    challenge = r.json()["challenge"]
    secret = client.post("/api/auth/totp/enroll", json={"challenge": challenge}).json()["secret"]
    r = client.post("/api/auth/totp/verify", json={"challenge": challenge, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    return secret


def _db():
    return next(db_module.get_db())


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["database"] == "ok"


def test_setup_creates_general_tenant_and_super_admin_once(client, admin_setup):
    assert admin_setup["role"] == "super_admin"
    assert admin_setup["email"] == "admin@example.com"
    db = _db()
    general = db.scalar(select(Tenant).where(Tenant.is_global.is_(True)))
    assert general is not None and general.slug == "general"
    assert client.get("/api/setup/status").json()["needs_setup"] is False
    again = client.post("/api/setup", json={"email": "x@example.com", "full_name": "X", "password": PASSWORD})
    assert again.status_code == 409


def test_setup_rejects_weak_password(client):
    r = client.post("/api/setup", json={"email": "a@example.com", "full_name": "A", "password": "short"})
    assert r.status_code == 422


def test_csrf_header_required(client):
    r = client.post("/api/setup", json={}, headers={"X-Mentis-Request": ""})
    assert r.status_code == 403


def test_login_requires_totp_enrollment_then_code(client, admin_setup):
    secret = _login_and_enroll(client)
    assert client.get("/api/auth/me").json()["totp_enabled"] is True

    client.post("/api/auth/logout")
    assert client.get("/api/auth/me").status_code == 401

    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert r.json()["next_step"] == "mfa_required"
    challenge = r.json()["challenge"]
    assert client.post("/api/auth/totp/verify", json={"challenge": challenge, "code": "000000"}).status_code == 401
    ok = client.post("/api/auth/totp/verify", json={"challenge": challenge, "code": pyotp.TOTP(secret).now()})
    assert ok.status_code == 200
    assert client.get("/api/auth/me").status_code == 200


def test_enroll_challenge_cannot_skip_to_session_without_code(client, admin_setup):
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    challenge = r.json()["challenge"]
    r = client.post("/api/auth/totp/verify", json={"challenge": challenge, "code": "123456"})
    assert r.status_code in (400, 401)
    assert client.get("/api/auth/me").status_code == 401


def test_tampered_challenge_rejected(client, admin_setup):
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    bad = r.json()["challenge"][:-2] + "xx"
    assert client.post("/api/auth/totp/enroll", json={"challenge": bad}).status_code == 401


def test_wrong_password_and_lockout(client, admin_setup):
    for _ in range(5):
        r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "Wrong-Password-1"})
        assert r.status_code == 401
    # Locked now: even the right password fails with the same generic message.
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid credentials."


def test_unknown_user_same_error(client, admin_setup):
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": PASSWORD})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid credentials."


def test_password_change(client, admin_setup):
    _login_and_enroll(client)
    weak = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "weak"})
    assert weak.status_code == 422
    wrong = client.post("/api/auth/password", json={"current_password": "nope", "new_password": "New-Strong-Pass-9"})
    assert wrong.status_code == 400
    ok = client.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "New-Strong-Pass-9"})
    assert ok.status_code == 204
    assert client.get("/api/auth/me").status_code == 200
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "New-Strong-Pass-9"})
    assert r.status_code == 200


def test_totp_secret_stored_encrypted(client, admin_setup):
    secret = _login_and_enroll(client)
    user = _db().scalar(select(User))
    assert user.totp_secret_enc and secret not in user.totp_secret_enc


def test_role_guard(client, admin_setup):
    app = client.app

    @app.get("/api/_test/analyst-only")
    def analyst_only(user=Depends(require_roles(Role.ANALYST))):
        return {"ok": True}

    @app.get("/api/_test/admin-only")
    def admin_only(user=Depends(require_roles(Role.SUPER_ADMIN))):
        return {"ok": True}

    assert client.get("/api/_test/admin-only").status_code == 401
    _login_and_enroll(client)
    assert client.get("/api/_test/admin-only").status_code == 200
    assert client.get("/api/_test/analyst-only").status_code == 403


def test_events_logged_without_secrets(client, admin_setup):
    _login_and_enroll(client)
    actions = {e.action for e in _db().scalars(select(AuditEvent))}
    assert {"setup.completed", "auth.mfa.enrolled", "auth.login.success"} <= actions
    for e in _db().scalars(select(AuditEvent)):
        assert PASSWORD not in str(e.detail)
