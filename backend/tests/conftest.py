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


@pytest.fixture
def admin_setup(client):
    r = client.post("/api/setup", json={"email": "Admin@Example.com", "full_name": "Admin", "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r.json()
