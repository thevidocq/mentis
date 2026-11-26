"""Authorization matrix: every API route × every kind of actor × objects of other tenants.

The route list comes from the application itself: a new route without an entry in ROUTES fails
`test_every_route_has_an_expectation`, so it cannot be forgotten.

World (built once per module): tenants AlfaCorp, BetaCorp and General, one document per tenant,
chats of several users, pending invitations per tenant, and the actors below. For each probe the
expected outcome is either a denial (401, 403 or 404) or ALLOW (any status that is not a denial
and not a server error). Every response, allowed or denied, is scanned for identifiers, names,
emails and document text of tenants, users, invitations and chats the actor must not see.

Probes that would destroy the world (deleting a user, a document, a chat, an invitation, logging
out, resetting another user's 2FA) run only where they must be denied; the allowed case is listed
as a skip with its reason, so the matrix still has an entry for it.
"""

import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core import db as db_module
from app.models import VersionPage
from tests.conftest import HEADERS, PASSWORD, login, new_client, run_jobs
from tests.fake_llm import FakeLLM
from tests.test_tenants_users import _invite_and_accept

ACTORS = ["anon", "sa", "ta_a", "ta_b", "ta_all", "an_a", "an_b", "an_g", "disabled"]
TAS = {"ta_a", "ta_b", "ta_all"}
ANALYSTS = {"an_a", "an_b", "an_g"}
CONTENT = TAS | ANALYSTS
LOGGED_OUT = {"anon", "disabled"}  # the disabled user's sessions were revoked when it was disabled
ALLOW = "allow"
DENIALS = {401, 403, 404}

EMAILS = {
    "sa": "root@example.com", "ta_a": "ta-alfa@example.com", "ta_b": "ta-beta@example.com",
    "ta_all": "ta-every@example.com", "an_a": "an-alfa@example.com", "an_b": "an-beta@example.com",
    "an_g": "an-gen@example.com", "disabled": "off-alfa@example.com",
}
# Tenants ticked per actor ("A", "B", "G"); ta_all has all_tenants plus the General Knowledge Base
# ticked (it manages it). an_g is an analyst without customers: like everyone, it reads the GKB.
TICKED = {"ta_a": {"A"}, "ta_b": {"B"}, "ta_all": {"A", "B", "G"}, "an_a": {"A"}, "an_b": {"B"},
          "an_g": set(), "disabled": {"A"}}
SECRET = {"A": "ALFASECRETXYZ", "B": "BETASECRETXYZ", "G": "GENERALSECRETXYZ"}
DOC_NAME = {"A": "AlfaRunbook.docx", "B": "BetaRunbook.docx", "G": "GeneralRunbook.docx"}
CHAT_OWNERS = ["an_a", "an_b", "an_g", "ta_a", "ta_all"]
CHAT_SCOPE = {"an_a": "A", "an_b": "B", "an_g": "G", "ta_a": "A", "ta_all": None}


def _qmark(owner: str) -> str:
    return f"QMARK<{owner}>"


@dataclass
class Probe:
    actor: str
    method: str
    path: str
    expect: Any  # ALLOW or an int status
    kw: dict = field(default_factory=dict)
    check: Callable | None = None  # extra assertion on an allowed response
    skip: str | None = None        # reason the allowed case is not executed
    shown: set = field(default_factory=set)  # forbidden tokens this probe may legitimately return (a shared chat)


@dataclass
class World:
    c: TestClient
    clients: dict
    t: dict           # "A"/"B"/"G" -> tenant id
    doc: dict         # tenant key -> document id
    ver: dict         # tenant key -> version id
    page: dict        # tenant key -> page index with an image
    chat: dict        # owner -> chat id
    msg: dict         # owner -> assistant message id
    share: dict       # owner -> share token of its chat
    inv: dict         # tenant key -> invitation id
    inv_email: dict   # tenant key -> invitation email
    uid: dict         # actor -> user id
    provider: str
    fake: FakeLLM


# --- World -------------------------------------------------------------------------

@pytest.fixture(scope="module")
def world():
    from qdrant_client import QdrantClient
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from app.main import create_app
    from app.models import Base
    from app.services import embeddings, jobs, llm, storage, vector_index
    from tests import fake_embeddings

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db_module.set_engine(engine)
    store = storage.MemoryStorage()
    storage.set_storage(store)
    queued: list = []
    jobs.set_runner(lambda name, vid: queued.append((name, vid)))
    vector_index.set_client(QdrantClient(":memory:"))
    embeddings.set_embedder(fake_embeddings.embed)
    fake = FakeLLM()
    llm.set_transport(fake.transport())
    try:
        app = create_app()
        app.state.auth_limiter = None  # thousands of sign-ins from one test client; the limiter has its own tests
        with TestClient(app) as c:
            c.headers.update(HEADERS)
            c.storage, c.queued = store, queued
            yield _build(c, fake)
    finally:
        llm.set_transport(None)
        storage.set_storage(None)
        jobs.set_runner(None)
        vector_index.set_client(None)
        embeddings.set_embedder(None)
        engine.dispose()


def _build(c: TestClient, fake: FakeLLM) -> World:
    assert c.post("/api/setup", json={"email": EMAILS["sa"], "full_name": "Root", "password": PASSWORD}).status_code == 201
    login(c, EMAILS["sa"])
    sa = c
    t = {"A": sa.post("/api/tenants", json={"name": "AlfaCorp"}).json()["id"],
         "B": sa.post("/api/tenants", json={"name": "BetaCorp"}).json()["id"],
         "G": next(x["id"] for x in sa.get("/api/tenants").json() if x["is_global"])}
    r = sa.post("/api/llm/providers", json={"name": "Claude", "kind": "anthropic", "base_url": "https://api.anthropic.com",
                                            "model": "claude-test", "api_key": "sk-secret-key", "options": {"price_in": 3}})
    provider = r.json()["id"]

    clients = {"sa": sa, "anon": new_client(c.app)}
    for actor in ["ta_a", "ta_b", "ta_all", "an_a", "an_b", "an_g", "disabled"]:
        role = "tenant_admin" if actor in TAS else "analyst"
        kw = ({"all_tenants": True, "tenant_ids": [t["G"]]} if actor == "ta_all"
              else {"tenant_ids": [t[k] for k in sorted(TICKED[actor])], "all_tenants": False})
        _invite_and_accept(sa, EMAILS[actor], role, name=f"User {actor}", **kw)
        cl = new_client(c.app)
        login(cl, EMAILS[actor])
        clients[actor] = cl
    uid = {u["email"]: u["id"] for u in sa.get("/api/users").json()}
    uid = {a: uid[e] for a, e in EMAILS.items()}

    # One document per tenant, uploaded by a tenant admin of that tenant.
    from tests.test_indexing import _docx, _upload

    uploader = {"A": "ta_a", "B": "ta_b", "G": "ta_all"}
    ver = {}
    for k in "ABG":
        ver[k] = _upload(clients[uploader[k]], t[k], DOC_NAME[k], _docx(f"{SECRET[k]} escalate brute force attacks to the on-call team"))["id"]
    run_jobs(c)
    # The General Knowledge Base always needs approval; ta_all manages it.
    assert clients["ta_all"].post(f"/api/tenants/{t['G']}/documents/versions/{ver['G']}/approve").status_code == 200
    doc, page = {}, {}
    for k in "ABG":
        docs = clients[uploader[k]].get(f"/api/tenants/{t[k]}/documents").json()
        doc[k] = docs[0]["id"]
        assert docs[0]["active"]["id"] == ver[k]
    # Give the first page of each version an image, so page-image probes have something to serve.
    db = next(db_module.get_db())
    from app.services import storage

    for k in "ABG":
        p = db.scalars(select(VersionPage).where(VersionPage.version_id == uuid.UUID(ver[k])).order_by(VersionPage.index)).first()
        p.image_key = storage.page_image_key(t[k], ver[k], p.index)
        storage.get_storage().put(p.image_key, f"PNG {SECRET[k]}".encode(), "image/png")
        page[k] = p.index
    db.commit()
    db.close()

    chat, msg = {}, {}
    for owner in CHAT_OWNERS:
        scope = CHAT_SCOPE[owner]
        r = clients[owner].post("/api/chats", json={"tenant_id": t[scope] if scope else None,
                                                    "message": f"{_qmark(owner)} brute force attacks escalate"})
        assert r.status_code == 201, r.text
        chat[owner], msg[owner] = r.json()["chat"]["id"], r.json()["answer"]["id"]
    assert r.json()["answer"]["status"] == "ok"  # ta_all, All customers: grounded answer
    share = {}
    for owner in CHAT_OWNERS:
        r = clients[owner].post(f"/api/chats/{chat[owner]}/share")
        assert r.status_code == 201, r.text
        share[owner] = r.json()["url"].rsplit("/", 1)[1]

    inv, inv_email = {}, {}
    for k in "ABG":
        inv_email[k] = f"pending-{k.lower()}@example.com"
        # For G: a tenant admin who will manage the General Knowledge Base.
        r = sa.post("/api/invitations", json={"email": inv_email[k], "full_name": "Pending",
                                              "role": "tenant_admin" if k == "G" else "analyst", "tenant_ids": [t[k]]})
        inv[k] = r.json()["id"]

    # Disable last: its client keeps a cookie whose session no longer exists.
    assert sa.patch(f"/api/users/{uid['disabled']}", json={"is_active": False}).status_code == 200
    return World(c=c, clients=clients, t=t, doc=doc, ver=ver, page=page, chat=chat, msg=msg, share=share, inv=inv,
                 inv_email=inv_email, uid=uid, provider=provider, fake=fake)


# --- Who may see what ------------------------------------------------------------

def sees(actor: str) -> set[str]:
    """Read access: the actor's customers plus the General Knowledge Base (everyone reads it)."""
    return (TICKED.get(actor, set()) | {"G"}) if actor in CONTENT else set()


def administers(actor: str, k: str) -> bool:
    """Customers it has; the GKB only when ticked explicitly."""
    return actor in TAS and k in TICKED[actor]


def manages(actor: str, target: str) -> bool:
    """users.can_manage: super-admins everyone; a tenant admin the content users whose customers it has all."""
    if actor == "sa":
        return True
    if actor not in TAS or target == "sa":
        return False
    if target == "ta_all":
        return actor == "ta_all"
    return TICKED[target] <= TICKED[actor]


def manages_invitation(actor: str, k: str) -> bool:
    return actor == "sa" or (actor in TAS and k in TICKED[actor])


def denial(actor: str, object_level: int = 404) -> int:
    """Status for an actor that may not use a route: logged out 401; wrong role 403; content role
    allowed on the route but not on this object `object_level`."""
    return 401 if actor in LOGGED_OUT else object_level


def forbidden_tokens(w: World, actor: str) -> dict[str, str]:
    """Strings that must never appear in a response to `actor` -> what they belong to."""
    out: dict[str, str] = {}
    visible = sees(actor)
    for k in "ABG":
        if actor == "sa":
            out[SECRET[k]] = f"document text of {k}"  # super-admins see no customer content
            continue
        if k in visible:
            continue
        out.update({w.t[k]: f"tenant id {k}", w.doc[k]: f"document id {k}", w.ver[k]: f"version id {k}",
                    DOC_NAME[k]: f"document name {k}", SECRET[k]: f"document text {k}"})
        if k != "G":
            out[{"A": "AlfaCorp", "B": "BetaCorp"}[k]] = f"tenant name {k}"
    for k in "ABG":
        if not manages_invitation(actor, k):
            out[w.inv[k]] = f"invitation id {k}"
            out[w.inv_email[k]] = f"invitation email {k}"
    for target, email in EMAILS.items():
        if target != actor and not manages(actor, target):
            out[email] = f"email of {target}"
    for owner in CHAT_OWNERS:
        if owner == actor:
            continue
        out[_qmark(owner)] = f"question of {owner}"
        if actor != "sa":  # the audit log names chats by id (metadata only)
            out[w.chat[owner]] = f"chat id of {owner}"
            out[w.msg[owner]] = f"message id of {owner}"
    return out


# --- Probes per route -----------------------------------------------------------------

def by_role(method: str, path: str, allowed: set[str], kw: dict | None = None, *, sa_kw: dict | None = None,
            check: Callable | None = None, allowed_status: Any = ALLOW) -> list[Probe]:
    out = []
    for a in ACTORS:
        if a in LOGGED_OUT:
            out.append(Probe(a, method, path, 401, kw or {}))
        elif a in allowed:
            out.append(Probe(a, method, path, allowed_status, (sa_kw if a == "sa" and sa_kw is not None else kw) or {}, check))
        else:
            out.append(Probe(a, method, path, 403, kw or {}))
    return out


def everyone(method: str, path: str, expect: Any, kw: dict | None = None) -> list[Probe]:
    return [Probe(a, method, path, expect, kw or {}) for a in ACTORS]


def super_only(method: str, path: str, sa_kw: dict | None = None, kw: dict | None = None, allowed_status: Any = ALLOW):
    return by_role(method, path, {"sa"}, kw, sa_kw=sa_kw, allowed_status=allowed_status)


def tenant_route(w: World, method: str, tmpl: str, kw: Callable[[str, str], dict] | None = None, *,
                 obj: bool = True, skip_allowed: str | None = None, allowed_status: Any = ALLOW) -> list[Probe]:
    """Routes under /tenants/{tenant_id}/documents: tenant admins of that tenant only.
    With `obj`, every object of every tenant is tried under every tenant id (IDOR)."""
    out = []
    pairs = [(k, o) for k in "ABG" for o in ("ABG" if obj else [k])]
    for a in ACTORS:
        for k, o in pairs:
            path = tmpl.format(t=w.t[k], doc=w.doc[o], ver=w.ver[o], page=w.page[o])
            body = kw(k, o) if kw else {}
            if a in LOGGED_OUT:
                out.append(Probe(a, method, path, 401, body))
            elif a not in TAS:
                out.append(Probe(a, method, path, 403, body))  # super-admins and analysts: no documents
            elif administers(a, k) and o == k:
                out.append(Probe(a, method, path, allowed_status, body, skip=skip_allowed))
            else:
                out.append(Probe(a, method, path, 404, body))
        if a in TAS:  # a tenant that does not exist
            out.append(Probe(a, method, tmpl.format(t=uuid.uuid4(), doc=w.doc["A"], ver=w.ver["A"], page=1), 404, kw("A", "A") if kw else {}))
    return out


def tenant_settings_route(w: World, method: str, tmpl: str, kw: dict, *, ta_denied: int, analyst_denied: int,
                          sa_status: Any = ALLOW, analyst_reads: bool = False, ta_allowed: bool = True) -> list[Probe]:
    out = []
    for a in ACTORS:
        for k in "ABG":
            path = tmpl.format(t=w.t[k])
            if a in LOGGED_OUT:
                exp = 401
            elif a == "sa":
                exp = sa_status
            elif a in TAS:
                # Reading a tenant (analyst_reads): every tenant the admin sees, the GKB included.
                exp = ALLOW if ta_allowed and (administers(a, k) or (analyst_reads and k in sees(a))) else ta_denied
            else:
                exp = ALLOW if analyst_reads and k in sees(a) else analyst_denied
            out.append(Probe(a, method, path, exp, kw))
    return out


def chat_route(w: World, method: str, tmpl: str, kw: dict | None = None, *, skip_allowed: str | None = None) -> list[Probe]:
    out = []
    for a in ACTORS:
        for owner in CHAT_OWNERS:
            path = tmpl.format(chat=w.chat[owner])
            if a in LOGGED_OUT:
                exp = 401
            elif a == "sa":
                exp = 403
            else:
                exp = ALLOW if a == owner else 404
            out.append(Probe(a, method, path, exp, kw or {}, skip=skip_allowed if exp == ALLOW else None))
    return out


def user_route(w: World, method: str, tmpl: str, kw: dict | None = None, *, allowed: Callable[[str, str], Any] = lambda a, t: ALLOW,
               skip_allowed: str | None = None, super_route: bool = False) -> list[Probe]:
    out = []
    for a in ACTORS:
        for target in EMAILS:
            path = tmpl.format(user=w.uid[target])
            if a in LOGGED_OUT:
                exp = 401
            elif super_route and a != "sa" or a in ANALYSTS:
                exp = 403
            elif manages(a, target):
                exp = allowed(a, target)
            else:
                exp = 404
            out.append(Probe(a, method, path, exp, kw or {}, skip=skip_allowed if exp not in DENIALS else None))
    return out


def no_provider_details(r):
    for p in r.json():
        assert p.get("base_url") is None and p.get("api_key_set") is None and p.get("options") is None and p.get("kind") is None, p


def no_costs(r):
    data = r.json()
    assert data["totals"]["cost_usd"] is None and all(row["cost_usd"] is None for row in data["rows"]), data


def _reset_link_status(a: str, target: str):
    if a == target:
        return 400
    if target == "disabled":
        return 409
    return 200


def _routes(w: World) -> dict[tuple[str, str], list[Probe]]:
    t, A = w.t, "/api"
    missing = {"challenge": "x" * 20, "code": "123456"}
    exist_email = EMAILS["an_a"]  # inviting an existing user stops at 409 after the access checks
    R: dict[tuple[str, str], list[Probe]] = {}

    def add(method, path, probes):
        R[(method, A + path)] = probes

    # Public
    add("GET", "/health", everyone("GET", A + "/health", 200))
    add("GET", "/setup/status", everyone("GET", A + "/setup/status", 200))
    add("POST", "/setup", everyone("POST", A + "/setup", 409, {"json": {"email": "new@example.com", "full_name": "X", "password": PASSWORD}}))
    add("POST", "/auth/login", everyone("POST", A + "/auth/login", 401, {"json": {"email": "nobody@example.com", "password": "x"}}))
    add("POST", "/auth/totp/enroll", everyone("POST", A + "/auth/totp/enroll", 401, {"json": {"challenge": missing["challenge"]}}))
    add("POST", "/auth/totp/verify", everyone("POST", A + "/auth/totp/verify", 401, {"json": missing}))
    add("POST", "/auth/password/forgot", everyone("POST", A + "/auth/password/forgot", 202, {"json": {"email": "nobody@example.com"}}))
    add("GET", "/auth/password/reset/{token}", everyone("GET", A + "/auth/password/reset/bogus-token", 404))
    add("POST", "/auth/password/reset/{token}", everyone("POST", A + "/auth/password/reset/bogus-token", 404, {"json": {"password": PASSWORD}}))
    add("GET", "/invitations/accept/{token}", everyone("GET", A + "/invitations/accept/bogus-token", 404))
    add("POST", "/invitations/accept/{token}", everyone("POST", A + "/invitations/accept/bogus-token", 404, {"json": {"password": PASSWORD}}))

    # Own account
    logged_in = set(ACTORS) - LOGGED_OUT
    add("GET", "/auth/me", by_role("GET", A + "/auth/me", logged_in))
    add("PATCH", "/auth/me", by_role("PATCH", A + "/auth/me", logged_in, {"json": {"theme": "dark"}}))
    add("POST", "/auth/password", by_role("POST", A + "/auth/password", logged_in,
                                          {"json": {"current_password": "wrong-Password-1", "new_password": PASSWORD}}, allowed_status=400))
    add("POST", "/auth/logout", [Probe(a, "POST", A + "/auth/logout", 401 if a in LOGGED_OUT else ALLOW,
                                       skip=None if a in LOGGED_OUT else "would end the actor's session") for a in ACTORS])

    # Tenants
    add("GET", "/tenants", by_role("GET", A + "/tenants", logged_in))
    add("POST", "/tenants", super_only("POST", A + "/tenants", sa_kw={"json": {"name": "Probe", "status": "bogus"}},
                                       kw={"json": {"name": "Probe"}}, allowed_status=422))
    add("GET", "/tenants/{tenant_id}", tenant_settings_route(w, "GET", A + "/tenants/{t}", {}, ta_denied=404, analyst_denied=404, analyst_reads=True))
    add("PATCH", "/tenants/{tenant_id}", tenant_settings_route(w, "PATCH", A + "/tenants/{t}", {"json": {"settings": {"suggested_followups": True}}},
                                                               ta_denied=403, analyst_denied=403))
    add("DELETE", "/tenants/{tenant_id}", tenant_settings_route(w, "DELETE", A + "/tenants/{t}", {"json": {"confirm_name": "wrong"}},
                                                                ta_denied=403, analyst_denied=403, sa_status=400, ta_allowed=False))
    add("GET", "/tenants/{tenant_id}/llm", tenant_settings_route(w, "GET", A + "/tenants/{t}/llm", {}, ta_denied=404, analyst_denied=404))
    add("PUT", "/tenants/{tenant_id}/llm", tenant_settings_route(w, "PUT", A + "/tenants/{t}/llm", {"json": {"provider_id": None, "fallback_id": None}},
                                                                 ta_denied=404, analyst_denied=404))

    # Users
    admins = {"sa"} | TAS
    add("GET", "/users", by_role("GET", A + "/users", admins))
    add("PATCH", "/users/{user_id}", user_route(w, "PATCH", A + "/users/{user}", {"json": {"full_name": "Same Name"}}))
    add("DELETE", "/users/{user_id}", user_route(w, "DELETE", A + "/users/{user}", skip_allowed="would delete a user of the world"))
    add("POST", "/users/{user_id}/password-reset", user_route(w, "POST", A + "/users/{user}/password-reset", allowed=_reset_link_status))
    reset2fa = [p for p in user_route(w, "POST", A + "/users/{user}/reset-2fa", super_route=True) if p.actor != "sa"]
    reset2fa.append(Probe("sa", "POST", f"{A}/users/{uuid.uuid4()}/reset-2fa", 404))  # allowed: would sign a world user out
    add("POST", "/users/{user_id}/reset-2fa", reset2fa)

    # Invitations
    add("GET", "/invitations", by_role("GET", A + "/invitations", admins))
    inv_create = []
    for a in ACTORS:
        for k in ["A", "B", "G", "all"]:
            body = {"json": {"email": exist_email, "full_name": "X", "role": "analyst",
                             "tenant_ids": [] if k == "all" else [t[k]], "all_tenants": k == "all"}}
            if a in LOGGED_OUT:
                exp = 401
            elif a == "sa" or (a in TAS and (a == "ta_all" if k == "all" else k in sees(a))):
                exp = 409
            else:
                exp = 403
            inv_create.append(Probe(a, "POST", A + "/invitations", exp, body))
    add("POST", "/invitations", inv_create)
    inv_delete = []
    for a in ACTORS:
        for k in "ABG":
            path = f"{A}/invitations/{w.inv[k]}"
            if a in LOGGED_OUT:
                inv_delete.append(Probe(a, "DELETE", path, 401))
            elif a in ANALYSTS:
                inv_delete.append(Probe(a, "DELETE", path, 403))
            elif manages_invitation(a, k):
                inv_delete.append(Probe(a, "DELETE", path, ALLOW, skip="would revoke a world invitation"))
            else:
                inv_delete.append(Probe(a, "DELETE", path, 404))
    add("DELETE", "/invitations/{invitation_id}", inv_delete)

    # Platform (super-admin only)
    add("GET", "/platform/smtp", super_only("GET", A + "/platform/smtp"))
    add("PUT", "/platform/smtp", super_only("PUT", A + "/platform/smtp", kw={"json": {}}))
    add("POST", "/platform/smtp/test", super_only("POST", A + "/platform/smtp/test", kw={"json": {"to": "x@example.com"}}, allowed_status=400))
    add("GET", "/platform/status", super_only("GET", A + "/platform/status"))
    add("GET", "/platform/embedding", super_only("GET", A + "/platform/embedding"))
    add("PUT", "/platform/embedding", super_only("PUT", A + "/platform/embedding", kw={"json": {}}))
    add("POST", "/platform/embedding/test", super_only("POST", A + "/platform/embedding/test"))
    add("POST", "/platform/embedding/reindex", super_only("POST", A + "/platform/embedding/reindex"))
    add("GET", "/platform/syslog", super_only("GET", A + "/platform/syslog"))
    add("PUT", "/platform/syslog", super_only("PUT", A + "/platform/syslog", kw={"json": {"enabled": False}}))
    add("POST", "/platform/syslog/test", super_only("POST", A + "/platform/syslog/test"))
    add("GET", "/platform/retention", super_only("GET", A + "/platform/retention"))
    add("PUT", "/platform/retention", super_only("PUT", A + "/platform/retention", kw={"json": {"chats_days": 365, "logs_days": 365}}))
    add("POST", "/platform/retention/purge", super_only("POST", A + "/platform/retention/purge"))
    add("GET", "/platform/config/export", super_only("GET", A + "/platform/config/export"))
    add("POST", "/platform/config/import", super_only("POST", A + "/platform/config/import", kw={"files": {"file": ("c.json", b"{}", "application/json")}}))
    for p in ["/logs", "/logs/actions", "/logs/export", "/logs/summary"]:
        add("GET", p, super_only("GET", A + p))

    # LLM providers
    add("GET", "/llm/kinds", super_only("GET", A + "/llm/kinds"))
    add("POST", "/llm/models", super_only("POST", A + "/llm/models", kw={"json": {"kind": "anthropic", "base_url": "https://api.anthropic.com"}}))
    add("GET", "/llm/providers", [p if p.actor != "sa" else Probe("sa", p.method, p.path, ALLOW)
                                  for p in by_role("GET", A + "/llm/providers", admins, check=no_provider_details)])
    bogus = {"json": {"name": "Bogus", "kind": "bogus", "base_url": "https://example.com", "model": "m"}}
    add("POST", "/llm/providers", super_only("POST", A + "/llm/providers", kw=bogus, allowed_status=422))
    add("PUT", "/llm/providers/{provider_id}", super_only("PUT", f"{A}/llm/providers/{w.provider}", kw=bogus, allowed_status=422))
    add("POST", "/llm/providers/{provider_id}/test", super_only("POST", f"{A}/llm/providers/{w.provider}/test"))
    pdel = [p for p in super_only("DELETE", f"{A}/llm/providers/{w.provider}") if p.actor != "sa"]
    pdel.append(Probe("sa", "DELETE", f"{A}/llm/providers/{uuid.uuid4()}", 404))  # allowed: would delete the world's provider
    add("DELETE", "/llm/providers/{provider_id}", pdel)

    # Usage: super-admins everything, tenant admins their customers without costs.
    add("GET", "/usage", [p if p.actor != "sa" else Probe("sa", p.method, p.path, ALLOW)
                          for p in by_role("GET", A + "/usage", admins, check=no_costs)])

    # Documents
    D = A + "/tenants/{t}/documents"
    add("GET", "/tenants/{tenant_id}/documents", tenant_route(w, "GET", D, obj=False))
    add("POST", "/tenants/{tenant_id}/documents", tenant_route(
        w, "POST", D, lambda k, o: {"files": {"file": ("x.docx", b"not a document", "application/octet-stream")}}, obj=False, allowed_status=422))
    add("GET", "/tenants/{tenant_id}/documents/{document_id}", tenant_route(w, "GET", D + "/{doc}"))
    add("PATCH", "/tenants/{tenant_id}/documents/{document_id}", tenant_route(w, "PATCH", D + "/{doc}", lambda k, o: {"json": {"name": DOC_NAME[o]}}))
    add("DELETE", "/tenants/{tenant_id}/documents/{document_id}", tenant_route(w, "DELETE", D + "/{doc}", skip_allowed="would delete a world document"))
    V = D + "/versions/{ver}"
    add("GET", "/tenants/{tenant_id}/documents/versions/{version_id}", tenant_route(w, "GET", V))
    add("GET", "/tenants/{tenant_id}/documents/versions/{version_id}/pages", tenant_route(w, "GET", V + "/pages"))
    add("GET", "/tenants/{tenant_id}/documents/versions/{version_id}/pages/{index}/image", tenant_route(w, "GET", V + "/pages/{page}/image"))
    add("GET", "/tenants/{tenant_id}/documents/versions/{version_id}/original", tenant_route(w, "GET", V + "/original"))
    add("POST", "/tenants/{tenant_id}/documents/versions/{version_id}/approve", tenant_route(w, "POST", V + "/approve", allowed_status=409))
    add("POST", "/tenants/{tenant_id}/documents/versions/{version_id}/reject", tenant_route(w, "POST", V + "/reject", allowed_status=409))
    add("POST", "/tenants/{tenant_id}/documents/versions/{version_id}/restore", tenant_route(w, "POST", V + "/restore"))
    add("POST", "/tenants/{tenant_id}/documents/versions/{version_id}/retry", tenant_route(w, "POST", V + "/retry", allowed_status=409))
    add("POST", "/tenants/{tenant_id}/documents/versions/{version_id}/search", tenant_route(
        w, "POST", V + "/search", lambda k, o: {"json": {"question": "brute force attacks"}}))

    # Chats: content roles; each chat only to its owner.
    add("GET", "/chats/scopes", by_role("GET", A + "/chats/scopes", CONTENT))
    add("GET", "/chats", by_role("GET", A + "/chats", CONTENT))
    new_chat = []
    for a in ACTORS:
        for k in ["A", "B", "G", None]:
            body = {"json": {"tenant_id": t[k] if k else None, "message": "brute force attacks escalate"}}
            if a in LOGGED_OUT:
                exp = 401
            elif a == "sa":
                exp = 403
            else:
                exp = 201 if k is None or k in sees(a) else 403
            new_chat.append(Probe(a, "POST", A + "/chats", exp, body))
    add("POST", "/chats", new_chat)
    add("GET", "/chats/{chat_id}", chat_route(w, "GET", A + "/chats/{chat}"))
    add("PATCH", "/chats/{chat_id}", chat_route(w, "PATCH", A + "/chats/{chat}", {"json": {"title": "Renamed"}}))
    add("DELETE", "/chats/{chat_id}", chat_route(w, "DELETE", A + "/chats/{chat}", skip_allowed="would delete a world chat"))
    add("POST", "/chats/{chat_id}/messages", chat_route(w, "POST", A + "/chats/{chat}/messages", {"json": {"message": "brute force attacks escalate"}}))
    feedback = []
    for a in ACTORS:
        for owner in CHAT_OWNERS:
            for mo in CHAT_OWNERS:  # message of another chat under this chat id (IDOR)
                path = f"{A}/chats/{w.chat[owner]}/messages/{w.msg[mo]}/feedback"
                if a in LOGGED_OUT:
                    exp = 401
                elif a == "sa":
                    exp = 403
                else:
                    exp = ALLOW if a == owner == mo else 404
                feedback.append(Probe(a, "POST", path, exp, {"json": {"value": None}}))
    add("POST", "/chats/{chat_id}/messages/{message_id}/feedback", feedback)

    # Share links: only the owner creates or revokes them (the allowed case would replace the world's link).
    add("GET", "/chats/{chat_id}/share", chat_route(w, "GET", A + "/chats/{chat}/share"))
    add("POST", "/chats/{chat_id}/share", chat_route(w, "POST", A + "/chats/{chat}/share", skip_allowed="would replace the world share link"))
    add("DELETE", "/chats/{chat_id}/share", chat_route(w, "DELETE", A + "/chats/{chat}/share", skip_allowed="would revoke the world share link"))
    # Opening a link: signed-in content roles that see the chat's customer.
    shared = []
    for a in ACTORS:
        for owner in CHAT_OWNERS + ["bogus"]:
            path = f"{A}/shared/{w.share.get(owner, 'not-a-real-token')}"
            scope = CHAT_SCOPE.get(owner)
            if a in LOGGED_OUT:
                exp = 401
            elif a == "sa":
                exp = 403
            elif owner == "bogus":
                exp = 404
            else:
                # An "All customers" chat (ta_all's searched A, B and G): only who sees all of them.
                exp = ALLOW if (scope in sees(a) if scope else {"A", "B", "G"} <= sees(a)) else 404
            # Its question and ids may show: every customer the answer can cite is seen.
            shown = {_qmark(owner), w.chat[owner], w.msg[owner]} if exp == ALLOW else set()
            shared.append(Probe(a, "GET", path, exp, shown=shown))
    add("GET", "/shared/{token}", shared)
    return R


# --- Route enumeration ---------------------------------------------------------------

def app_routes(app) -> set[tuple[str, str]]:
    """(METHOD, path) of every HTTP route of the app, including routers included with a prefix."""
    found: set[tuple[str, str]] = set()

    def walk(routes):
        for r in routes:
            if hasattr(r, "effective_route_contexts"):  # FastAPI >= 0.16x: included routers
                walk(r.effective_route_contexts())
            elif hasattr(r, "routes") and not hasattr(r, "methods"):
                walk(r.routes)
            elif getattr(r, "methods", None) and getattr(r, "path", None):
                for m in r.methods - {"HEAD", "OPTIONS"}:
                    found.add((m, r.path))
    walk(app.routes)
    return found


def test_every_route_has_an_expectation(world):
    routes = app_routes(world.c.app)
    assert len(routes) >= 80
    expected = set(_routes(world))
    missing, stale = sorted(routes - expected), sorted(expected - routes)
    assert not missing, f"Routes without an authorization expectation (add them to _routes): {missing}"
    assert not stale, f"Expectations for routes that no longer exist: {stale}"


def test_authorization_matrix(world):
    routes = _routes(world)
    failures: list[str] = []
    coverage: dict[tuple, set] = defaultdict(set)
    executed = skipped = 0
    tokens = {a: forbidden_tokens(world, a) for a in ACTORS}
    for key, probes in routes.items():
        assert probes, key
        for p in probes:
            coverage[key].add(p.actor)
            if p.skip and p.expect not in DENIALS:
                skipped += 1
                continue
            executed += 1
            r = world.clients[p.actor].request(p.method, p.path, **p.kw)
            where = f"{p.actor:8} {p.method} {p.path}"
            if p.expect == ALLOW:
                if r.status_code in DENIALS or r.status_code >= 500:
                    failures.append(f"{where}: expected allowed, got {r.status_code} {r.text[:150]}")
                    continue
                if p.check and r.status_code < 300:
                    try:
                        p.check(r)
                    except AssertionError as e:
                        failures.append(f"{where}: {e}")
            elif r.status_code != p.expect:
                failures.append(f"{where}: expected {p.expect}, got {r.status_code} {r.text[:150]}")
                continue
            body = r.content.decode("utf-8", "replace")
            leaked = [f"{what} ({tok})" for tok, what in tokens[p.actor].items() if tok in body and tok not in p.shown]
            if leaked:
                failures.append(f"{where}: response {r.status_code} leaks {leaked}")
    for key, actors in coverage.items():
        if actors != set(ACTORS):
            failures.append(f"{key}: no probe for {sorted(set(ACTORS) - actors)}")
    print(f"\nauthz matrix: {len(routes)} routes x {len(ACTORS)} actors, {executed} requests, {skipped} allowed-destructive skips")
    assert not failures, "\n".join(failures[:80]) + (f"\n... {len(failures) - 80} more" if len(failures) > 80 else "")


def test_world_sanity(world):
    """The world really holds what the matrix relies on: each chat answered from its own tenants."""
    ta_all = world.clients["ta_all"]
    chat = ta_all.get(f"/api/chats/{world.chat['ta_all']}").json()
    assert chat["messages"][1]["citations"], chat
    an_a = world.clients["an_a"].get(f"/api/chats/{world.chat['an_a']}").json()
    # Alfa's own document or the General Knowledge Base (everyone reads it), never Beta.
    content = an_a["messages"][1]["content"]
    assert (SECRET["A"] in content or SECRET["G"] in content) and SECRET["B"] not in str(an_a)
