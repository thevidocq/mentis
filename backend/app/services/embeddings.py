"""Embeddings through any OpenAI-compatible endpoint (POST {base}/embeddings).

Works with Hugging Face TEI (default, bge-m3 in the `embeddings` container), Ollama, vLLM
or a cloud provider. Settings: platform setting "embedding" over environment defaults.
"""

from collections.abc import Callable

import httpx
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import get_settings
from app.models import PlatformSetting

EMBED_KEY = "embedding"

Embedder = Callable[[list[str]], list[list[float]]]
_override: Embedder | None = None


class EmbeddingError(RuntimeError):
    pass


class EmbeddingModelChanged(EmbeddingError):
    """The configured model differs from the one the index was built with (a message for users)."""


def set_embedder(embedder: Embedder | None) -> None:
    """Tests replace the HTTP client with an in-process function."""
    global _override
    _override = embedder


def get_config(db: Session) -> dict:
    s = get_settings()
    row = db.get(PlatformSetting, EMBED_KEY)
    stored = dict(row.value) if row else {}
    api_key = crypto.decrypt(stored["api_key_enc"]) if stored.get("api_key_enc") else s.embedding_api_key
    return {
        "url": stored.get("url") or s.embedding_url,
        "model": stored.get("model") or s.embedding_model,
        "api_key": api_key,
        # Recorded when the index was last built, to detect a model change.
        "indexed_model": stored.get("indexed_model"),
        "indexed_dim": stored.get("indexed_dim"),
    }


def public_config(cfg: dict) -> dict:
    return {
        "url": cfg["url"],
        "model": cfg["model"],
        "api_key_set": bool(cfg["api_key"]),
        "indexed_model": cfg["indexed_model"],
        "indexed_dim": cfg["indexed_dim"],
        "reindex_needed": bool(cfg["indexed_model"]) and cfg["indexed_model"] != cfg["model"],
    }


def save_config(db: Session, url: str | None, model: str | None, api_key: str | None) -> dict:
    row = db.get(PlatformSetting, EMBED_KEY)
    value = dict(row.value) if row else {}
    if url is not None:
        value["url"] = url.rstrip("/")
    if model is not None:
        value["model"] = model.strip()
    if api_key is not None:
        value["api_key_enc"] = crypto.encrypt(api_key) if api_key else None
    if row is None:
        db.add(PlatformSetting(key=EMBED_KEY, value=value))
    else:
        row.value = value
    db.commit()
    return get_config(db)


def record_index(db: Session, model: str, dim: int) -> None:
    row = db.get(PlatformSetting, EMBED_KEY)
    value = dict(row.value) if row else {}
    value.update(indexed_model=model, indexed_dim=dim)
    if row is None:
        db.add(PlatformSetting(key=EMBED_KEY, value=value))
    else:
        row.value = value
    db.commit()


def embed(cfg: dict, texts: list[str]) -> list[list[float]]:
    """Embed texts in batches. Raises EmbeddingError with a readable message."""
    if not texts:
        return []
    if _override is not None:
        return _override(texts)
    s = get_settings()
    headers = {"Authorization": f"Bearer {cfg['api_key']}"} if cfg.get("api_key") else {}
    out: list[list[float]] = []
    try:
        with httpx.Client(timeout=s.embedding_timeout_seconds) as client:
            for i in range(0, len(texts), s.embedding_batch_size):
                batch = texts[i : i + s.embedding_batch_size]
                r = client.post(f"{cfg['url']}/embeddings", json={"model": cfg["model"], "input": batch}, headers=headers)
                if r.status_code != 200:
                    body = r.text.replace(cfg["api_key"], "[redacted]") if cfg.get("api_key") else r.text  # a key echoed back
                    raise EmbeddingError(f"Embedding service answered {r.status_code}: {body[:200]}")
                data = sorted(r.json()["data"], key=lambda d: d["index"])
                if len(data) != len(batch):
                    raise EmbeddingError("Embedding service returned a wrong number of vectors.")
                out.extend(d["embedding"] for d in data)
    except httpx.HTTPError as e:
        raise EmbeddingError(f"Embedding service not reachable at {cfg['url']}: {e.__class__.__name__}") from None
    except (KeyError, ValueError, TypeError) as e:
        raise EmbeddingError(f"Unexpected answer from the embedding service: {e}") from None
    return out
