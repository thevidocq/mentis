import os
import re

os.environ["MENTIS_SECRET_KEY"] = "test-secret-key-0123456789"
os.environ["MENTIS_COOKIE_SECURE"] = "false"
os.environ["MENTIS_WEB_SETUP"] = "true"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from app.core import db as db_module
from app.main import create_app
from app.models import Base, Tenant

HEADERS = {"X-Mentis-Request": "1"}
PASSWORD = "Correct-Horse-42"


@pytest.fixture
def client():
    from qdrant_client import QdrantClient

    from app.services import embeddings, jobs, storage, vector_index
    from tests import fake_embeddings

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db_module.set_engine(engine)
    # In-memory object storage and inline job execution (no MinIO/Redis in tests).
    store = storage.MemoryStorage()
    storage.set_storage(store)
    queued: list[tuple[str, str]] = []
    jobs.set_runner(lambda name, vid: queued.append((name, vid)))
    # In-memory Qdrant and deterministic embeddings (no services needed).
    vector_index.set_client(QdrantClient(":memory:"))
    embeddings.set_embedder(fake_embeddings.embed)
    with TestClient(create_app()) as c:
        c.headers.update(HEADERS)
        c.storage = store
        c.queued = queued
        yield c
    storage.set_storage(None)
    jobs.set_runner(None)
    vector_index.set_client(None)
    embeddings.set_embedder(None)
    engine.dispose()


def run_jobs(c):
    """Process every queued ingestion job, like the worker would."""
    from app.worker.tasks import ingest_version, reindex_all, reprocess_all

    while c.queued:
        name, vid = c.queued.pop(0)
        ingest_version(vid) if name == "ingest" else (reprocess_all() if name == "reprocess" else reindex_all())


def approve_general(c):
    """Process queued jobs, then approve the General Knowledge Base versions waiting for it
    (they always need approval) through the API, like a tenant admin who manages it."""
    from sqlalchemy import select as _select

    from app.core import db as _db
    from app.models import DocumentVersion, Tenant as _Tenant
    from app.models.document import Approval

    run_jobs(c)
    db = next(_db.get_db())
    gkb = db.scalar(_select(_Tenant).where(_Tenant.is_global.is_(True)))
    pending = db.scalars(_select(DocumentVersion.id).where(DocumentVersion.tenant_id == gkb.id,
                                                            DocumentVersion.approval == Approval.PENDING)).all()
    db.close()
    for vid in pending:
        r = c.post(f"/api/tenants/{gkb.id}/documents/versions/{vid}/approve")
        assert r.status_code == 200, r.text


def login(c, email, password=PASSWORD):
    """Full login (enrolling TOTP if needed). Returns the TOTP secret."""
    import pyotp

    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    challenge = r.json()["challenge"]
    secret = c.post("/api/auth/totp/enroll", json={"challenge": challenge}).json()["secret"]
    r = c.post("/api/auth/totp/verify", json={"challenge": challenge, "code": pyotp.TOTP(secret).now()})
    if r.status_code == 401 and "already used" in r.text:  # same user signed in twice within 30 s
        import time
        r = c.post("/api/auth/totp/verify", json={"challenge": challenge, "code": pyotp.TOTP(secret).at(time.time() + 30)})
    assert r.status_code == 200, r.text
    return secret


def new_client(app):
    c = TestClient(app)
    c.headers.update(HEADERS)
    return c


CONTENT_PATHS = re.compile(r"^/api/(chats\b|tenants/[^/]+/documents\b)")


@pytest.fixture
def super_admin(client, admin_setup):
    """`client` logged in as the super-admin.

    Super-admins see no customer content, so for convenience the requests to documents and
    chats made through this client go to `client.content`: a tenant admin of all customers.
    Use `client.direct(method, url, ...)` to send them as the super-admin itself.
    """
    from app.core.security import hash_password
    from app.models import User

    login(client, "admin@example.com")
    db = next(db_module.get_db())
    content_admin = User(email="content@example.com", full_name="Content Admin", password_hash=hash_password(PASSWORD),
                         role="tenant_admin", all_tenants=True)
    # All customers, and the General Knowledge Base ticked explicitly (to manage it).
    content_admin.tenants = [t for t in db.scalars(select(Tenant)) if t.is_global]
    db.add(content_admin)
    db.commit()
    db.close()
    content = new_client(client.app)
    login(content, "content@example.com")
    client.content = content
    original = client.request
    client.direct = original

    def routed(method, url, *args, **kwargs):
        target = content.request if CONTENT_PATHS.match(str(url).split("?")[0]) else original
        return target(method, url, *args, **kwargs)

    client.request = routed
    return client


@pytest.fixture
def admin_setup(client):
    r = client.post("/api/setup", json={"email": "Admin@Example.com", "full_name": "Admin", "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()
