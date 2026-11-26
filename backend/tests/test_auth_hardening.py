"""Regression tests for authentication fixes (lockout, TOTP replay, bad input, timing, invitations)."""

from datetime import timedelta

import pyotp
from sqlalchemy import select, update

from app.api.routes import auth as auth_routes
from app.core import db as db_module
from app.core.config import get_settings
from app.models import Invitation, User
from app.models.base import utcnow
from app.services import sessions
from tests.conftest import PASSWORD, login, new_client
from tests.test_tenants_users import _create_tenant, _invite_and_accept


def _db():
    return next(db_module.get_db())


def test_failed_logins_count_in_database_not_on_stale_object(client, admin_setup):
    # Parallel attempts each hold a stale copy of the user: the count must still add up.
    db = _db()
    user = db.scalar(select(User).where(User.email == "admin@example.com"))
    assert user.failed_logins == 0
    db.execute(update(User).where(User.id == user.id).values(failed_logins=get_settings().max_failed_logins - 1)
               .execution_options(synchronize_session=False))
    db.commit()
    assert user.failed_logins == 0  # stale, like a request that loaded it earlier
    sessions.register_failed_login(db, user)
    assert sessions.is_locked(user)


def test_totp_step_is_claimed_once(client, admin_setup):
    db = _db()
    user = db.scalar(select(User).where(User.email == "admin@example.com"))
    other = _db()
    stale = other.get(User, user.id)
    assert sessions.claim_totp_step(db, user, 100) is True
    # A parallel request that read the user before the first one stored the step.
    assert stale.totp_last_step is None
    assert sessions.claim_totp_step(other, stale, 100) is False
    assert sessions.claim_totp_step(other, stale, 101) is True


def test_non_ascii_code_and_challenge_are_refused_not_crash(client, admin_setup):
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    challenge = r.json()["challenge"]
    client.post("/api/auth/totp/enroll", json={"challenge": challenge})
    r = client.post("/api/auth/totp/verify", json={"challenge": challenge, "code": "١٢٣٤٥٦"})
    assert r.status_code == 401
    r = client.post("/api/auth/totp/verify", json={"challenge": challenge.split(".")[0] + ".é", "code": "123456"})
    assert r.status_code == 401
    r = client.post("/api/auth/totp/enroll", json={"challenge": "x.é"})
    assert r.status_code == 401


def test_disabled_or_locked_login_spends_a_password_check(client, admin_setup, monkeypatch):
    db = _db()
    db.execute(update(User).where(User.email == "admin@example.com").values(locked_until=utcnow() + timedelta(minutes=5)))
    db.commit()
    calls = []
    real = auth_routes.verify_password
    monkeypatch.setattr(auth_routes, "verify_password", lambda p, h: calls.append(1) or real(p, h))
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": PASSWORD})
    assert r.status_code == 401
    assert calls == [1]


def test_expired_pending_invitation_does_not_block_a_new_one(super_admin):
    alfa, beta = _create_tenant(super_admin, "Alfa"), _create_tenant(super_admin, "Beta")
    _invite_and_accept(super_admin, "ta@example.com", "tenant_admin", tenant_id=alfa["id"])
    ta = new_client(super_admin.app)
    login(ta, "ta@example.com")
    r = super_admin.post("/api/invitations", json={"email": "x@example.com", "full_name": "X", "role": "analyst",
                                                   "tenant_ids": [beta["id"]]})
    assert r.status_code == 201
    body = {"email": "x@example.com", "full_name": "X", "role": "analyst", "tenant_ids": [alfa["id"]]}
    assert ta.post("/api/invitations", json=body).status_code == 409  # still pending, not theirs
    db = _db()
    db.execute(update(Invitation).where(Invitation.email == "x@example.com").values(expires_at=utcnow() - timedelta(hours=1)))
    db.commit()
    assert ta.post("/api/invitations", json=body).status_code == 201


def _stale_lookup(model, monkeypatch, svc):
    """Emulate two submits of one link in parallel: both pass the validity check before either commits."""
    from app.core.security import hash_token

    def find(db, token):
        row = db.scalar(select(model).where(model.token_hash == hash_token(token)))
        if model is Invitation:
            return row
        return row, db.get(User, row.user_id)

    monkeypatch.setattr(svc, "find_valid", find)


def test_password_reset_link_used_twice_in_parallel_works_once(super_admin, monkeypatch):
    from app.models import PasswordReset
    from app.services import password_reset as reset_svc

    _invite_and_accept(super_admin, "an@example.com", "analyst")
    uid = next(u["id"] for u in super_admin.get("/api/users").json() if u["email"] == "an@example.com")
    token = super_admin.post(f"/api/users/{uid}/password-reset").json()["reset_url"].rsplit("/", 1)[1]
    anon = new_client(super_admin.app)
    assert anon.post(f"/api/auth/password/reset/{token}", json={"password": "First-Passw0rd!"}).status_code == 204
    _stale_lookup(PasswordReset, monkeypatch, reset_svc)
    assert anon.post(f"/api/auth/password/reset/{token}", json={"password": "Second-Passw0rd!"}).status_code == 404
    r = anon.post("/api/auth/login", json={"email": "an@example.com", "password": "First-Passw0rd!"})
    assert r.status_code == 200


def test_invitation_accepted_twice_in_parallel_is_not_a_500(super_admin, monkeypatch):
    from app.services import invitations as inv_svc
    from app.services import users as user_rules

    r = super_admin.post("/api/invitations", json={"email": "x@example.com", "full_name": "X", "role": "analyst",
                                                   "all_tenants": True})
    token = r.json()["invite_url"].rsplit("/", 1)[1]
    anon = new_client(super_admin.app)
    assert anon.post(f"/api/invitations/accept/{token}", json={"password": PASSWORD}).status_code == 201
    _stale_lookup(Invitation, monkeypatch, inv_svc)
    monkeypatch.setattr(user_rules, "email_in_use", lambda db, email: False)
    assert anon.post(f"/api/invitations/accept/{token}", json={"password": PASSWORD}).status_code in (404, 409)


def test_forgot_password_without_smtp_keeps_the_admin_link(super_admin):
    _invite_and_accept(super_admin, "an@example.com", "analyst")
    uid = next(u["id"] for u in super_admin.get("/api/users").json() if u["email"] == "an@example.com")
    r = super_admin.post(f"/api/users/{uid}/password-reset")
    assert r.json()["email_sent"] is False
    token = r.json()["reset_url"].rsplit("/", 1)[1]
    anon = new_client(super_admin.app)
    # Nothing can be emailed: the sign-in page request must not replace the link shared by the admin.
    assert anon.post("/api/auth/password/forgot", json={"email": "an@example.com"}).status_code == 202
    assert anon.get(f"/api/auth/password/reset/{token}").status_code == 200
