from sqlalchemy import select

from app.core import db as db_module
from app.models import AuditEvent
from app.services import invitations as inv_svc
from tests.conftest import PASSWORD, login, new_client


def _db():
    return next(db_module.get_db())


def _general(c):
    return next(t for t in c.get("/api/tenants").json() if t["is_global"])


def _create_tenant(c, name="Cliente Alfa"):
    r = c.post("/api/tenants", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _invite_and_accept(c, email, role, tenant_id=None, name="User", tenant_ids=None, all_tenants=None):
    ids = tenant_ids if tenant_ids is not None else ([tenant_id] if tenant_id else [])
    if all_tenants is None:  # an analyst without customers given sees them all, as before 0.3.0
        all_tenants = role == "analyst" and not ids
    r = c.post("/api/invitations", json={"email": email, "full_name": name, "role": role, "tenant_ids": ids, "all_tenants": all_tenants})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["email_sent"] is False and body["invite_url"]  # no SMTP configured in tests
    token = body["invite_url"].rsplit("/", 1)[1]
    anon = new_client(c.app)
    assert anon.get(f"/api/invitations/accept/{token}").json()["email"] == email
    r = anon.post(f"/api/invitations/accept/{token}", json={"password": PASSWORD})
    assert r.status_code == 201, r.text
    return token


# --- Tenants -----------------------------------------------------------------

def test_create_list_and_slug(super_admin):
    t = _create_tenant(super_admin, "Cliente Alfa S.p.A.")
    assert t["slug"] == "cliente-alfa-s-p-a"
    assert t["status"] == "onboarding"
    assert t["settings"]["require_approval"] is False
    names = [x["name"] for x in super_admin.get("/api/tenants").json()]
    assert names[0] == "General" and "Cliente Alfa S.p.A." in names
    assert super_admin.post("/api/tenants", json={"name": "cliente alfa s.p.a."}).status_code == 409


def test_update_tenant_and_settings(super_admin):
    t = _create_tenant(super_admin)
    r = super_admin.patch(f"/api/tenants/{t['id']}", json={"name": "Alfa", "status": "active", "settings": {"require_approval": True}})
    assert r.status_code == 200
    assert r.json()["name"] == "Alfa" and r.json()["settings"]["require_approval"] is True
    assert super_admin.patch(f"/api/tenants/{t['id']}", json={"settings": {"bogus": True}}).status_code == 422


def test_general_cannot_be_deleted_or_disabled(super_admin):
    g = _general(super_admin)
    r = super_admin.request("DELETE", f"/api/tenants/{g['id']}", json={"confirm_name": "General"})
    assert r.status_code == 400
    assert super_admin.patch(f"/api/tenants/{g['id']}", json={"status": "disabled"}).status_code == 400


def test_delete_requires_exact_name_and_removes_users(super_admin):
    t = _create_tenant(super_admin)
    _invite_and_accept(super_admin, "ta@example.com", "tenant_admin", t["id"])
    assert super_admin.request("DELETE", f"/api/tenants/{t['id']}", json={"confirm_name": "cliente alfa"}).status_code == 400
    assert super_admin.request("DELETE", f"/api/tenants/{t['id']}", json={"confirm_name": "Cliente Alfa"}).status_code == 204
    assert all(u["email"] != "ta@example.com" for u in super_admin.get("/api/users").json())
    actions = [e.action for e in _db().scalars(select(AuditEvent))]
    assert "tenant.deleted" in actions


# --- Invitations and roles -----------------------------------------------------

def test_tenant_admin_scope(super_admin):
    alfa = _create_tenant(super_admin, "Alfa")
    beta = _create_tenant(super_admin, "Beta")
    _invite_and_accept(super_admin, "ta@example.com", "tenant_admin", alfa["id"])

    ta = new_client(super_admin.app)
    login(ta, "ta@example.com")
    # Sees only its own tenant.
    assert [t["name"] for t in ta.get("/api/tenants").json()] == ["Alfa"]
    assert ta.get(f"/api/tenants/{beta['id']}").status_code == 404
    # Can change its own settings but not rename or touch other tenants.
    assert ta.patch(f"/api/tenants/{alfa['id']}", json={"settings": {"include_general": False}}).status_code == 200
    assert ta.patch(f"/api/tenants/{alfa['id']}", json={"name": "Hacked"}).status_code == 403
    assert ta.patch(f"/api/tenants/{beta['id']}", json={"settings": {"include_general": False}}).status_code == 403
    assert ta.post("/api/tenants", json={"name": "Gamma"}).status_code == 403
    # Can invite tenant admins for its own tenant only.
    ok = ta.post("/api/invitations", json={"email": "ta2@example.com", "full_name": "B", "role": "tenant_admin", "tenant_ids": [alfa["id"]]})
    assert ok.status_code == 201
    assert ta.post("/api/invitations", json={"email": "x@example.com", "full_name": "X", "role": "tenant_admin", "tenant_ids": [beta["id"]]}).status_code == 403
    # It can invite analysts too, on its own customers only, and never for all customers.
    assert ta.post("/api/invitations", json={"email": "y@example.com", "full_name": "Y", "role": "analyst", "tenant_ids": [alfa["id"]]}).status_code == 201
    assert ta.post("/api/invitations", json={"email": "z@example.com", "full_name": "Z", "role": "analyst", "all_tenants": True}).status_code == 403
    assert ta.post("/api/invitations", json={"email": "w@example.com", "full_name": "W", "role": "super_admin"}).status_code == 403
    # Sees only the users it can manage (itself included): not the super-admin nor the content admin of all customers.
    assert {u["email"] for u in ta.get("/api/users").json()} == {"ta@example.com"}


def test_analyst_sees_its_tenants_but_cannot_admin(super_admin):
    alfa = _create_tenant(super_admin, "Alfa")
    _create_tenant(super_admin, "Beta")
    g = _general(super_admin)
    _invite_and_accept(super_admin, "an@example.com", "analyst", tenant_ids=[alfa["id"], g["id"]])
    an = new_client(super_admin.app)
    login(an, "an@example.com")
    assert [t["name"] for t in an.get("/api/tenants").json()] == ["General", "Alfa"]
    assert an.get("/api/users").status_code == 403
    assert an.post("/api/invitations", json={"email": "z@example.com", "full_name": "Z", "role": "analyst"}).status_code == 403


def test_invitation_validation(super_admin):
    g = _general(super_admin)
    bad = [
        {"email": "a@example.com", "full_name": "A", "role": "tenant_admin"},                           # no customer
        {"email": "a@example.com", "full_name": "A", "role": "analyst"},                                # no customer
        {"email": "a@example.com", "full_name": "A", "role": "super_admin", "tenant_ids": [g["id"]]},  # super-admin with customers
        {"email": "a@example.com", "full_name": "A", "role": "wizard"},
    ]
    for body in bad:
        assert super_admin.post("/api/invitations", json=body).status_code == 422, body
    assert super_admin.post("/api/invitations", json={"email": "admin@example.com", "full_name": "A", "role": "analyst", "all_tenants": True}).status_code == 409
    # General alone is a valid customer for a tenant admin (it manages the shared documentation).
    assert super_admin.post("/api/invitations", json={"email": "g@example.com", "full_name": "G", "role": "tenant_admin", "tenant_ids": [g["id"]]}).status_code == 201


def test_invitation_token_single_use_and_revocable(super_admin):
    token = _invite_and_accept(super_admin, "an@example.com", "analyst")
    anon = new_client(super_admin.app)
    assert anon.get(f"/api/invitations/accept/{token}").status_code == 404
    r = super_admin.post("/api/invitations", json={"email": "other@example.com", "full_name": "O", "role": "analyst", "all_tenants": True})
    inv_id = r.json()["id"]
    assert super_admin.delete(f"/api/invitations/{inv_id}").status_code == 204
    assert super_admin.get("/api/invitations").json() == []


def test_invitation_sent_by_smtp(super_admin, monkeypatch):
    sent = []
    monkeypatch.setattr(inv_svc.mail, "send_mail", lambda cfg, to, subject, body: sent.append((to, body)))
    super_admin.put("/api/platform/smtp", json={"host": "smtp.example.com", "port": 587, "security": "starttls",
                                                 "username": "u", "password": "p", "from_address": "mentis@example.com"})
    r = super_admin.post("/api/invitations", json={"email": "an@example.com", "full_name": "An", "role": "analyst", "all_tenants": True})
    assert r.json()["email_sent"] is True and r.json()["invite_url"] is None
    assert sent and sent[0][0] == "an@example.com" and "/invite/" in sent[0][1]


# --- Users ---------------------------------------------------------------------

def test_last_super_admin_protected(super_admin):
    me = super_admin.get("/api/auth/me").json()
    assert super_admin.patch(f"/api/users/{me['id']}", json={"is_active": False}).status_code == 400
    assert super_admin.patch(f"/api/users/{me['id']}", json={"role": "analyst", "all_tenants": True}).status_code == 400
    assert super_admin.delete(f"/api/users/{me['id']}").status_code == 400


def test_deactivate_user_revokes_sessions(super_admin):
    _invite_and_accept(super_admin, "an@example.com", "analyst")
    an = new_client(super_admin.app)
    login(an, "an@example.com")
    uid = next(u["id"] for u in super_admin.get("/api/users").json() if u["email"] == "an@example.com")
    assert super_admin.patch(f"/api/users/{uid}", json={"is_active": False}).status_code == 200
    assert an.get("/api/auth/me").status_code == 401


def test_reset_2fa_forces_new_enrollment(super_admin):
    _invite_and_accept(super_admin, "an@example.com", "analyst")
    an = new_client(super_admin.app)
    login(an, "an@example.com")
    uid = next(u["id"] for u in super_admin.get("/api/users").json() if u["email"] == "an@example.com")
    assert super_admin.post(f"/api/users/{uid}/reset-2fa").status_code == 204
    r = an.post("/api/auth/login", json={"email": "an@example.com", "password": PASSWORD})
    assert r.json()["next_step"] == "mfa_enrollment"


# --- Account and SMTP settings -----------------------------------------------

def test_profile_and_theme(super_admin):
    r = super_admin.patch("/api/auth/me", json={"full_name": "New Name", "theme": "light"})
    assert r.status_code == 200 and r.json()["preferences"]["theme"] == "light"
    assert super_admin.patch("/api/auth/me", json={"theme": "neon"}).status_code == 422


def test_smtp_password_never_returned(super_admin):
    r = super_admin.put("/api/platform/smtp", json={"host": "smtp.example.com", "password": "s3cret", "from_address": "m@example.com"})
    assert r.status_code == 200
    data = super_admin.get("/api/platform/smtp").json()
    assert data["password_set"] is True and "s3cret" not in str(data)
    assert data["configured"] is True
