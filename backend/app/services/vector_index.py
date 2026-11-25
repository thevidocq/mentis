"""Qdrant index: one collection per tenant, one point per chunk.

Payload: tenant_id, document_id, version_id, chunk_id, active.
PostgreSQL stays the source of truth: search results are re-checked against the database,
so a stale `active` flag in Qdrant can never surface a version that is not in use.
"""

import os
import uuid
from functools import lru_cache

from qdrant_client import QdrantClient, models

from app.core.config import get_settings

_override: QdrantClient | None = None


class VectorIndexError(RuntimeError):
    pass


def set_client(client: QdrantClient | None) -> None:
    global _override
    _override = client


@lru_cache
def _default() -> QdrantClient:
    s = get_settings()
    return QdrantClient(url=s.qdrant_url, api_key=s.qdrant_api_key, timeout=30)


def client() -> QdrantClient:
    return _override or _default()


def collection_name(tenant_id) -> str:
    return f"mentis_{uuid.UUID(str(tenant_id)).hex}"


def _match(key: str, value) -> models.FieldCondition:
    return models.FieldCondition(key=key, match=models.MatchValue(value=str(value) if isinstance(value, uuid.UUID) else value))


def ensure_collection(tenant_id, dim: int) -> str:
    name = collection_name(tenant_id)
    c = client()
    if c.collection_exists(name):
        size = c.get_collection(name).config.params.vectors.size
        if size != dim:
            raise VectorIndexError(f"The embedding model changed (vector size {size} → {dim}). Reindex from Embedding and Qdrant.")
        return name
    c.create_collection(name, vectors_config=models.VectorParams(size=dim, distance=models.Distance.COSINE))
    for key in ("document_id", "version_id"):
        c.create_payload_index(name, key, models.PayloadSchemaType.KEYWORD)
    c.create_payload_index(name, "active", models.PayloadSchemaType.BOOL)
    return name


def upsert_chunks(tenant_id, document_id, version_id, active: bool, chunks: list[tuple[uuid.UUID, list[float]]]) -> None:
    if not chunks:
        return
    name = ensure_collection(tenant_id, len(chunks[0][1]))
    points = [
        models.PointStruct(id=str(chunk_id), vector=vec, payload={
            "tenant_id": str(tenant_id), "document_id": str(document_id), "version_id": str(version_id),
            "chunk_id": str(chunk_id), "active": active,
        })
        for chunk_id, vec in chunks
    ]
    for i in range(0, len(points), 256):
        client().upsert(name, points=points[i : i + 256], wait=True)


def _exists(tenant_id) -> bool:
    return client().collection_exists(collection_name(tenant_id))


def delete_version(tenant_id, version_id) -> None:
    if _exists(tenant_id):
        client().delete(collection_name(tenant_id), points_selector=models.Filter(must=[_match("version_id", version_id)]), wait=True)


def delete_document(tenant_id, document_id) -> None:
    if _exists(tenant_id):
        client().delete(collection_name(tenant_id), points_selector=models.Filter(must=[_match("document_id", document_id)]), wait=True)


def delete_tenant(tenant_id) -> None:
    if _exists(tenant_id):
        client().delete_collection(collection_name(tenant_id))


def sync_active(tenant_id, document_id, active_version_id) -> None:
    """Mark only `active_version_id` as active among a document's points (None = no active version)."""
    if not _exists(tenant_id):
        return
    name = collection_name(tenant_id)
    if active_version_id is not None:
        client().set_payload(name, payload={"active": True}, wait=True,
                             points=models.Filter(must=[_match("version_id", active_version_id)]))
    others = models.Filter(must=[_match("document_id", document_id)],
                           must_not=[_match("version_id", active_version_id)] if active_version_id else None)
    client().set_payload(name, payload={"active": False}, points=others, wait=True)


def search(tenant_id, vector: list[float], limit: int, version_id=None, active_only: bool = True) -> list[models.ScoredPoint]:
    """Raises VectorIndexError when Qdrant is unreachable or refuses the query (e.g. wrong vector size)."""
    must = [_match("tenant_id", tenant_id)]
    if version_id is not None:
        must.append(_match("version_id", version_id))
    elif active_only:
        must.append(_match("active", True))
    try:
        if not _exists(tenant_id):
            return []
        return client().query_points(collection_name(tenant_id), query=vector, query_filter=models.Filter(must=must),
                                     limit=limit, with_payload=True).points
    except Exception as e:  # noqa: BLE001 - connection errors and Qdrant rejections alike
        raise VectorIndexError(f"The vector index (Qdrant) could not be searched: {e.__class__.__name__}") from None


def stats() -> dict:
    c = client()
    names = [col.name for col in c.get_collections().collections if col.name.startswith("mentis_")]
    return {"collections": len(names), "points": sum(c.count(n, exact=False).count for n in names)}


# A forked job process gets its own Qdrant client instead of the parent's HTTP connections.
if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_default.cache_clear)
