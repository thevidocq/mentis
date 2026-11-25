import pytest

from app import cli
from app.core import db as db_module
from app.core.config import get_settings
from tests.conftest import PASSWORD, login


@pytest.fixture
def web_setup_off():
    s = get_settings()
    s.web_setup = False
    yield
    s.web_setup = True


def test_web_setup_off_by_default_points_to_cli(client, web_setup_off):
    st = client.get("/api/setup/status").json()
    assert st == {"needs_setup": True, "web_setup": False}
    r = client.post("/api/setup", json={"email": "a@example.com", "full_name": "A", "password": PASSWORD})
    assert r.status_code == 403 and "create-admin" in r.json()["detail"]


def test_cli_create_admin(client, web_setup_off, monkeypatch, capsys):
    pw = iter([PASSWORD, PASSWORD])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(pw))
    cli.create_admin(next(db_module.get_db()), "Admin@Example.com", "Admin")
    assert "created" in capsys.readouterr().out
    assert client.get("/api/setup/status").json()["needs_setup"] is False
    login(client, "admin@example.com")
    assert client.get("/api/auth/me").json()["role"] == "super_admin"
    assert any(t["is_global"] for t in client.get("/api/tenants").json())
    # A second run is refused.
    with pytest.raises(SystemExit, match="already exists"):
        cli.create_admin(next(db_module.get_db()), "b@example.com", "B")


def test_cli_rejects_weak_or_mismatched_password(client, monkeypatch):
    pw = iter(["short", "short"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(pw))
    with pytest.raises(SystemExit):
        cli.create_admin(next(db_module.get_db()), "a@example.com", "A")
    pw2 = iter([PASSWORD, PASSWORD + "x"])
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(pw2))
    with pytest.raises(SystemExit, match="do not match"):
        cli.create_admin(next(db_module.get_db()), "a@example.com", "A")
    assert client.get("/api/setup/status").json()["needs_setup"] is True
