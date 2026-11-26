"""Startup refusal of placeholder secrets and production defaults of the API."""

import pytest
from pydantic import ValidationError

from app.core.config import DEV_SECRET_KEY, Settings

GOOD = {
    "secret_key": "0123456789abcdef0123456789abcdef",
    "database_url": "postgresql+psycopg://mentis:s3cret-db@postgres:5432/mentis",
    "redis_url": "redis://:s3cret-redis@redis:6379/0",
    "minio_secret_key": "s3cret-minio",
    "qdrant_api_key": "s3cret-qdrant",
}


def make(**overrides) -> Settings:
    return Settings(_env_file=None, **{**GOOD, **overrides})


@pytest.fixture(autouse=True)
def no_env(monkeypatch):
    monkeypatch.delenv("MENTIS_SECRET_KEY", raising=False)
    monkeypatch.delenv("MENTIS_ENV", raising=False)


def test_production_settings_with_real_secrets_start():
    assert make().env == "production"


def test_builtin_dev_secret_key_refused_in_production():
    with pytest.raises(ValidationError, match="MENTIS_SECRET_KEY is not set"):
        Settings(_env_file=None, **{k: v for k, v in GOOD.items() if k != "secret_key"})


@pytest.mark.parametrize("env", ["development", "test", "DEV"])
def test_builtin_dev_secret_key_allowed_for_development(env):
    s = Settings(_env_file=None, env=env)
    assert s.secret_key == DEV_SECRET_KEY


@pytest.mark.parametrize("field,value,name", [
    ("secret_key", "CHANGE_ME_CHANGE_ME_CHANGE_ME", "MENTIS_SECRET_KEY"),
    ("minio_secret_key", "CHANGE_ME_min_8_chars", "MINIO_ROOT_PASSWORD"),
    ("qdrant_api_key", "CHANGE_ME", "QDRANT_API_KEY"),
    ("database_url", "postgresql+psycopg://mentis:CHANGE_ME@postgres:5432/mentis", "POSTGRES_PASSWORD"),
    ("redis_url", "redis://:CHANGE_ME@redis:6379/0", "REDIS_PASSWORD"),
])
def test_env_example_placeholders_refused(field, value, name):
    with pytest.raises(ValidationError, match=name):
        make(**{field: value})


def test_env_variable_drives_the_check(monkeypatch):
    monkeypatch.setenv("MENTIS_ENV", "development")
    assert Settings(_env_file=None).secret_key == DEV_SECRET_KEY
    monkeypatch.setenv("MENTIS_ENV", "production")
    with pytest.raises(ValidationError, match="MENTIS_ENV=development"):
        Settings(_env_file=None)


def test_api_docs_and_openapi_are_off_by_default(client):
    assert client.get("/api/docs").status_code == 404
    assert client.get("/api/openapi.json").status_code == 404


def test_no_cors_for_other_origins(client):
    r = client.options("/api/auth/login", headers={"Origin": "https://evil.example",
                                                   "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers
    r = client.get("/api/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in r.headers
