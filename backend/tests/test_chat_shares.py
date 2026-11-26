"""Sharing a chat by link: read-only, for signed-in colleagues who see the chat's customer."""

from datetime import timedelta

from sqlalchemy import select

from app.core import db as db_module
from app.models import AuditEvent, ChatShare
from app.models.base import utcnow
from tests.conftest import login, new_client
from tests.test_chat import _provider, _setup
from tests.test_chat import fake_llm as _fake_llm
from tests.test_tenants_users import _invite_and_accept

fake_llm = _fake_llm  # the fixture, under its name


def _user(sa, email, role, **kw):
    _invite_and_accept(sa, email, role, **kw)
    c = new_client(sa.app)
    login(c, email)
    return c


def _world(sa):
    _provider(sa)
    alfa, beta = _setup(sa)
    owner = _user(sa, "owner@example.com", "analyst", tenant_ids=[alfa["id"]], all_tenants=False, name="Owner Name")
    mate = _user(sa, "mate@example.com", "analyst", tenant_ids=[alfa["id"]], all_tenants=False)
    other = _user(sa, "other@example.com", "analyst", tenant_ids=[beta["id"]], all_tenants=False)
    chat = owner.post("/api/chats", json={"tenant_id": alfa["id"], "message": "Who handles brute force escalation?"}).json()
    return alfa, beta, owner, mate, other, chat


def _token(url):
    return url.rsplit("/", 1)[1]


def test_share_view_and_revoke(super_admin, fake_llm):
    alfa, beta, owner, mate, other, ex = _world(super_admin)
    cid = ex["chat"]["id"]
    assert owner.get(f"/api/chats/{cid}/share").json()["active"] is False
    assert owner.get(f"/api/chats/{cid}").json()["shared"] is False
    owner.post(f"/api/chats/{cid}/messages/{ex['answer']['id']}/feedback", json={"value": "up"})

    r = owner.post(f"/api/chats/{cid}/share")
    assert r.status_code == 201 and r.json()["url"].startswith("http") and "/shared/" in r.json()["url"]
    tok = _token(r.json()["url"])
    assert owner.get(f"/api/chats/{cid}").json()["shared"] is True
    assert owner.get(f"/api/chats/{cid}/share").json() | {"expires_at": None} == {"url": None, "active": True, "expires_at": None}

    v = mate.get(f"/api/shared/{tok}")
    assert v.status_code == 200, v.text
    body = v.json()
    assert body["owner_name"] == "Owner Name" and body["scope_name"] == "Alfa" and body["hidden"] == 0
    assert [m["role"] for m in body["messages"]] == ["user", "assistant"]
    assert "Mario Rossi" in body["messages"][1]["content"] and body["messages"][1]["feedback"] is None
    assert body["messages"][1]["citations"]
    # The owner may open its own link; a colleague of another customer, a super-admin and anonymous may not.
    assert owner.get(f"/api/shared/{tok}").status_code == 200
    assert other.get(f"/api/shared/{tok}").status_code == 404
    assert super_admin.direct("GET", f"/api/shared/{tok}").status_code == 403
    assert new_client(super_admin.app).get(f"/api/shared/{tok}").status_code == 401
    # Not even the viewer can create or revoke the owner's link.
    assert mate.post(f"/api/chats/{cid}/share").status_code == 404
    assert mate.delete(f"/api/chats/{cid}/share").status_code == 404

    # A new link replaces the old one.
    tok2 = _token(owner.post(f"/api/chats/{cid}/share").json()["url"])
    assert mate.get(f"/api/shared/{tok}").status_code == 404 and mate.get(f"/api/shared/{tok2}").status_code == 200
    # Revoked.
    assert owner.delete(f"/api/chats/{cid}/share").status_code == 204
    assert mate.get(f"/api/shared/{tok2}").status_code == 404
    assert owner.get(f"/api/chats/{cid}").json()["shared"] is False

    db = next(db_module.get_db())
    actions = [e.action for e in db.scalars(select(AuditEvent).where(AuditEvent.action.like("chat.share%")))]
    db.close()
    for a in ("chat.shared", "chat.share_viewed", "chat.share_denied", "chat.share_revoked"):
        assert a in actions, actions


def test_expired_link_and_disabled_owner(super_admin, fake_llm):
    alfa, beta, owner, mate, other, ex = _world(super_admin)
    cid = ex["chat"]["id"]
    tok = _token(owner.post(f"/api/chats/{cid}/share").json()["url"])
    db = next(db_module.get_db())
    row = db.scalars(select(ChatShare)).one()
    row.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    assert mate.get(f"/api/shared/{tok}").status_code == 404
    assert owner.get(f"/api/chats/{cid}").json()["shared"] is False
    row.expires_at = utcnow() + timedelta(days=1)
    db.commit()
    assert mate.get(f"/api/shared/{tok}").status_code == 200
    # Only a hash of the token is stored.
    assert row.token_hash != tok and tok not in row.token_hash
    db.close()

    # The owner is disabled: its links stop working.
    uid = next(u["id"] for u in super_admin.get("/api/users").json() if u["email"] == "owner@example.com")
    assert super_admin.patch(f"/api/users/{uid}", json={"is_active": False}).status_code == 200
    assert mate.get(f"/api/shared/{tok}").status_code == 404


def test_deleting_the_chat_deletes_its_links(super_admin, fake_llm):
    alfa, beta, owner, mate, other, ex = _world(super_admin)
    cid = ex["chat"]["id"]
    tok = _token(owner.post(f"/api/chats/{cid}/share").json()["url"])
    assert owner.delete(f"/api/chats/{cid}").status_code == 204
    assert mate.get(f"/api/shared/{tok}").status_code == 404
    db = next(db_module.get_db())
    assert db.scalars(select(ChatShare)).all() == []
    db.close()


def test_all_customers_chat_needs_every_customer(super_admin, fake_llm):
    _provider(super_admin)
    alfa, beta = _setup(super_admin)
    owner = _user(super_admin, "owner@example.com", "analyst", tenant_ids=[alfa["id"], beta["id"]], all_tenants=False)
    only_alfa = _user(super_admin, "a@example.com", "analyst", tenant_ids=[alfa["id"]], all_tenants=False)
    both = _user(super_admin, "ab@example.com", "analyst", tenant_ids=[alfa["id"], beta["id"]], all_tenants=False)
    ex = owner.post("/api/chats", json={"tenant_id": None, "message": "brute force escalation"}).json()
    tok = _token(owner.post(f"/api/chats/{ex['chat']['id']}/share").json()["url"])
    # The answer searched Alfa and Beta: whoever lacks one of them cannot open it.
    assert only_alfa.get(f"/api/shared/{tok}").status_code == 404
    assert both.get(f"/api/shared/{tok}").status_code == 200
