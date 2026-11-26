"""Application settings, read from environment variables."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MENTIS_", env_file=".env", extra="ignore")

    # Database URL, e.g. postgresql+psycopg://user:pass@postgres:5432/mentis
    database_url: str = "sqlite:///./mentis-dev.db"

    # Secret used to sign short-lived MFA challenge tokens. Must be long and random in production.
    secret_key: str = Field(default="dev-only-change-me", min_length=16)

    # Session cookie settings.
    session_cookie_name: str = "mentis_session"
    session_ttl_hours: int = 12
    # Set to False only for local HTTP testing; behind HTTPS keep True.
    cookie_secure: bool = True
    # First super-admin from the browser. Off: use `python -m app.cli create-admin` on the server.
    web_setup: bool = False
    # Interactive API documentation at /api/docs (development only).
    api_docs: bool = False

    # MFA challenge lifetime (between password check and TOTP code).
    mfa_challenge_ttl_seconds: int = 300

    # Login lockout.
    max_failed_logins: int = 5
    lockout_minutes: int = 15

    # Issuer name shown in authenticator apps.
    totp_issuer: str = "Mentis"

    # Object storage (MinIO) for original documents and page images.
    minio_endpoint: str = "minio:9000"
    minio_access_key: str = "mentis"
    minio_secret_key: str = "change-me"
    minio_bucket: str = "mentis-documents"
    minio_secure: bool = False

    # Job queue (Redis) for the ingestion worker.
    redis_url: str = "redis://redis:6379/0"

    # Upload limits.
    max_upload_mb: int = 50
    # Uncompressed size limit for DOCX/PPTX/XLSX (zip containers), against zip bombs.
    max_unzipped_mb: int = 300
    # Parsing limits per version.
    max_pages: int = 1000
    ingest_timeout_seconds: int = 1800

    # Vector database.
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str | None = None

    # Embeddings: any OpenAI-compatible /embeddings endpoint (TEI, Ollama, vLLM, OpenAI).
    # These are the defaults; the super-admin can change them in the panel.
    embedding_url: str = "http://embeddings/v1"
    embedding_model: str = "BAAI/bge-m3"
    embedding_api_key: str | None = None
    embedding_batch_size: int = 32
    embedding_timeout_seconds: int = 120

    # Chat retrieval: passages sent to the LLM and the minimum similarity to keep one.
    chat_passages: int = 8
    chat_min_score: float = 0.3

    # Base URL users open in the browser; used to build invitation links.
    public_url: str = "http://localhost"
    invitation_ttl_hours: int = 72
    password_reset_ttl_minutes: int = 60          # link emailed from the sign-in page
    password_reset_admin_ttl_hours: int = 24      # link created by an admin


@lru_cache
def get_settings() -> Settings:
    return Settings()
