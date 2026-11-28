"""Embeddings through any OpenAI-compatible endpoint (POST {base}/embeddings).

Works with Hugging Face TEI (default, bge-m3 in the `embeddings` container), Ollama, vLLM
or a cloud provider. Settings: platform setting "embedding" over environment defaults.
"""

from collections.abc import Callable

import math

import httpx
from sqlalchemy.orm import Session

from app.core import crypto
from app.core.config import get_settings
from app.models import PlatformSetting

EMBED_KEY = "embedding"

Embedder = Callable[[list[str]], list[list[float]]]
_override: Embedder | None = None


class EmbeddingError(RuntimeError):
    """`public` marks a message safe to show to analysts and tenant admins (no URL, no service reply)."""

    def __init__(self, message: str, public: bool = False):
        super().__init__(message)
        self.public = public


class EmbeddingSettingRefused(ValueError):
    """A change of the embedding settings that is not allowed (shown to the super-admin)."""


MAX_DIM = 8192           # no embedding model has more dimensions
MAX_RESPONSE = 64 << 20  # bytes of one embedding answer


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
    url = stored.get("url") or s.embedding_url
    if stored.get("api_key_enc"):
        api_key = crypto.decrypt(stored["api_key_enc"])
    else:  # the key from .env goes only to the address from .env
        from app.services.llm_config import same_origin

        api_key = s.embedding_api_key if same_origin(url, s.embedding_url) else None
    return {
        "url": url,
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


def allowed_url(url: str) -> bool:
    """Whether the embedding service may be moved to `url` (MENTIS_EMBEDDING_ALLOWED_URLS)."""
    from app.services.llm_config import same_origin

    s = get_settings()
    allowed = [u.strip() for u in (s.embedding_allowed_urls or "").split(",") if u.strip()]
    return not allowed or same_origin(url, s.embedding_url) or any(same_origin(url, a) for a in allowed)


def save_config(db: Session, url: str | None, model: str | None, api_key: str | None) -> dict:
    """Raises EmbeddingSettingRefused for an address that is not allowed, or a new address with a
    stored key and no key given: a stored key is only ever sent to the origin it was saved for."""
    from app.services.llm_config import same_origin

    row = db.get(PlatformSetting, EMBED_KEY)
    value = dict(row.value) if row else {}
    if url is not None:
        url = url.rstrip("/")
        if not allowed_url(url):
            raise EmbeddingSettingRefused("This address is not in MENTIS_EMBEDDING_ALLOWED_URLS: every document and "
                                          "question is sent to the embedding service, so its address is set in .env.")
        current = get_config(db)
        if not same_origin(url, current["url"]):
            if api_key is None and current["api_key"]:
                raise EmbeddingSettingRefused("The address changed: enter the API key again (leave it empty for a "
                                              "service without a key). A saved key is only sent to the address it was saved for.")
            if api_key is None:
                value["api_key_enc"] = None
        value["url"] = url
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
                with client.stream("POST", f"{cfg['url']}/embeddings", json={"model": cfg["model"], "input": batch},
                                   headers=headers) as r:
                    body = _read_capped(r)
                if r.status_code != 200:
                    text = body.decode("utf-8", "replace")
                    text = text.replace(cfg["api_key"], "[redacted]") if cfg.get("api_key") else text  # a key echoed back
                    raise EmbeddingError(f"Embedding service answered {r.status_code}: {text[:200]}")
                import json

                out.extend(_vectors(json.loads(body)["data"], len(batch), out))
    except httpx.HTTPError as e:
        raise EmbeddingError(f"Embedding service not reachable at {cfg['url']}: {e.__class__.__name__}") from None
    except (KeyError, ValueError, TypeError) as e:
        raise EmbeddingError(f"Unexpected answer from the embedding service: {str(e)[:200]}") from None
    return out


def _read_capped(r: httpx.Response) -> bytes:
    chunks, size = [], 0
    for chunk in r.iter_bytes():
        size += len(chunk)
        if size > MAX_RESPONSE:
            raise EmbeddingError("Embedding service returned an answer too large.")
        chunks.append(chunk)
    return b"".join(chunks)


def _vectors(data, n: int, before: list) -> list[list[float]]:
    """The vectors of one batch, checked: one per text in order (indices 0..n-1, each once), every
    value a finite number, every vector of the call the same size (the index checks its own size)."""
    if not isinstance(data, list) or len(data) != n:
        raise EmbeddingError("Embedding service returned a wrong number of vectors.")
    if sorted(d.get("index") if isinstance(d, dict) else None for d in data if isinstance(d, dict)) != list(range(n)) \
            or len(data) != sum(isinstance(d, dict) for d in data):
        raise EmbeddingError("Embedding service returned vectors in an unreadable order.")
    dim = len(before[0]) if before else None
    out = []
    for d in sorted(data, key=lambda d: d["index"]):
        v = d.get("embedding")
        if not isinstance(v, list) or not v or len(v) > MAX_DIM or (dim is not None and len(v) != dim):
            raise EmbeddingError("Embedding service returned a vector of the wrong size.")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in v):
            raise EmbeddingError("Embedding service returned a vector with invalid values.")
        dim = len(v)
        out.append([float(x) for x in v])
    return out
