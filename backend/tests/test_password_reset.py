"""Forgotten password: emailed link, admin link, one use, 2FA still required."""

import re

import pyotp

from app.services import password_reset as svc
from tests.conftest import PASSWORD, new_client
from tests.test_access import _user
from tests.test_indexing import _tenant

NEW = "Brand-New-Passw0rd!"


def _smtp(sa, monkeypatch):
    sent = []
    monkeypatch.setattr(svc.mail, "send_mail", lambda cfg, to, subject, body: sent.append((to, body)))
    sa.put("/api/platform/smtp", json={"host": "smtp.example.com", "port": 587, "security": "starttls",
                                       "username": "u", "password": "p", "from_address": "mentis@example.com"})
    return sent


def _token(body: str) -> str:
    return re.search(r"/reset/(\S+)", body).group(1)


def test_forgot_password_by_email_keeps_2fa(super_admin, monkeypatch):
    an = _user(super_admin, "an@example.com", "analyst", all_tenants=True)
    sent = _smtp(super_admin, monkeypatch)
    anon = new_client(super_admin.app)
    # Same answer for unknown and known emails.
    a = anon.post("/api/auth/password/forgot", json={"email": "nobody@example.com"})
    b = anon.post("/api/auth/password/forgot", json={"email": "AN@example.com"})
    assert a.status_code == b.status_code == 202 and a.json() == b.json()
    assert len(sent) == 1 and sent[0][0] == "an@example.com"
    # A second request right away sends nothing.
    anon.post("/api/auth/password/forgot", json={"email": "an@example.com"})
    assert len(sent) == 1
    token = _token(sent[0][1])
    assert anon.get(f"/api/auth/password/reset/{token}").json()["email"] == "an@example.com"
    assert anon.post(f"/api/auth/password/reset/{token}", json={"password": "short"}).status_code == 422
    assert anon.post(f"/api/auth/password/reset/{token}", json={"password": NEW}).status_code == 204
    # Used once only; old sessions are closed; the old password no longer works.
    assert anon.post(f"/api/auth/password/reset/{token}", json={"password": NEW}).status_code == 404
    assert an.get("/api/auth/me").status_code == 401
    assert anon.post("/api/auth/login", json={"email": "an@example.com", "password": PASSWORD}).status_code == 401
    # The new password leads to the 2FA step, not to a session.
    r = anon.post("/api/auth/login", json={"email": "an@example.com", "password": NEW})
    assert r.status_code == 200 and r.json()["next_step"] == "mfa_required"
    r = anon.post("/api/auth/totp/verify", json={"challenge": r.json()["challenge"], "code": pyotp.TOTP(an.secret).at(0)})
    assert r.status_code == 401


def test_admin_link_without_smtp(super_admin):
    alfa, beta = _tenant(super_admin, "Alfa"), _tenant(super_admin, "Beta")
    an = _user(super_admin, "an@example.com", "analyst", tenant_ids=[alfa["id"]])
    other = _user(super_admin, "other@example.com", "analyst", tenant_ids=[beta["id"]])
    ta = _user(super_admin, "ta@example.com", "tenant_admin", tenant_ids=[alfa["id"]])
    users = {u["email"]: u["id"] for u in super_admin.get("/api/users").json()}
    r = ta.post(f"/api/users/{users['an@example.com']}/password-reset")
    assert r.status_code == 200 and r.json()["email_sent"] is False and "/reset/" in r.json()["reset_url"]
    # A tenant admin cannot create links for users it does not manage, nor for itself.
    assert ta.post(f"/api/users/{users['other@example.com']}/password-reset").status_code == 404
    assert ta.post(f"/api/users/{users['ta@example.com']}/password-reset").status_code == 400
    # The analyst cannot create links at all.
    assert an.post(f"/api/users/{users['other@example.com']}/password-reset").status_code == 403
    token = r.json()["reset_url"].rsplit("/", 1)[1]
    anon = new_client(super_admin.app)
    assert anon.post(f"/api/auth/password/reset/{token}", json={"password": NEW}).status_code == 204
    assert other.get("/api/auth/me").status_code == 200  # nobody else was signed out
    events = [e["action"] for e in super_admin.get("/api/logs").json()["items"]]
    assert "user.password_reset_link" in events and "auth.password.reset" in events


def test_reset_unlocks_and_disabled_users_get_no_link(super_admin, monkeypatch):
    _user(super_admin, "an@example.com", "analyst", all_tenants=True)
    sent = _smtp(super_admin, monkeypatch)
    anon = new_client(super_admin.app)
    for _ in range(5):
        anon.post("/api/auth/login", json={"email": "an@example.com", "password": "wrong-Passw0rd!"})
    anon.post("/api/auth/password/forgot", json={"email": "an@example.com"})
    anon.post(f"/api/auth/password/reset/{_token(sent[-1][1])}", json={"password": NEW})
    assert anon.post("/api/auth/login", json={"email": "an@example.com", "password": NEW}).status_code == 200
    uid = next(u["id"] for u in super_admin.get("/api/users").json() if u["email"] == "an@example.com")
    super_admin.patch(f"/api/users/{uid}", json={"is_active": False})
    n = len(sent)
    anon.post("/api/auth/password/forgot", json={"email": "an@example.com"})
    assert len(sent) == n
    assert super_admin.post(f"/api/users/{uid}/password-reset").status_code == 409


def test_password_too_long_is_refused(super_admin):
    from app.core.security import password_problem

    assert "at most" in password_problem("Aa1" + "x" * 300)
    anon = new_client(super_admin.app)
    assert anon.post("/api/auth/login", json={"email": "a@example.com", "password": "x" * 5000}).status_code == 422
