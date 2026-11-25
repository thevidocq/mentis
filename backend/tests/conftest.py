import os

os.environ["MENTIS_SECRET_KEY"] = "test-secret-key-0123456789"
os.environ["MENTIS_COOKIE_SECURE"] = "false"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.core import db as db_module
from app.main import create_app
from app.models import Base

HEADERS = {"X-Mentis-Request": "1"}
PASSWORD = "Correct-Horse-42"


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    db_module.set_engine(engine)
    with TestClient(create_app()) as c:
        c.headers.update(HEADERS)
        yield c
    engine.dispose()


def login(c, email, password=PASSWORD):
    """Full login (enrolling TOTP if needed). Returns the TOTP secret."""
    import pyotp

    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    challenge = r.json()["challenge"]
    secret = c.post("/api/auth/totp/enroll", json={"challenge": challenge}).json()["secret"]
    r = c.post("/api/auth/totp/verify", json={"challenge": challenge, "code": pyotp.TOTP(secret).now()})
    assert r.status_code == 200, r.text
    return secret


def new_client(app):
    c = TestClient(app)
    c.headers.update(HEADERS)
    return c


@pytest.fixture
def super_admin(client, admin_setup):
    """`client` logged in as the super-admin."""
    login(client, "admin@example.com")
    return client


@pytest.fixture
def admin_setup(client):
    r = client.post("/api/setup", json={"email": "Admin@Example.com", "full_name": "Admin", "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()
