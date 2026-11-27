"""Retrieval: find the passages that answer a question.

Every hit from Qdrant is re-checked against PostgreSQL (chunk exists, belongs to the expected
tenant and version, version ready and — for answers — active). The database decides; the
index only proposes.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Chunk,
    Document,
    DocumentVersion,
    Tenant,
    VersionPage,
    VersionStatus,
)
from app.services import diversity, embeddings, indexing, vector_index


@dataclass
class Passage:
    score: float
    tenant_id: uuid.UUID
    tenant_name: str
    is_general: bool
    document_id: uuid.UUID
    document_name: str
    version_id: uuid.UUID
    version: int
    page_index: int
    page_label: str
    heading: str | None
    text: str
    chunk_id: uuid.UUID | None = None


def _passages(db: Session, hits, *, active_only: bool, version_id=None) -> list[Passage]:
    scores = {uuid.UUID(h.payload["chunk_id"]): h.score for h in hits if h.payload and h.payload.get("chunk_id")}
    if not scores:
        return []
    rows = db.execute(
        select(Chunk, DocumentVersion, Document, Tenant)
        .join(DocumentVersion, DocumentVersion.id == Chunk.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .join(Tenant, Tenant.id == DocumentVersion.tenant_id)
        .where(Chunk.id.in_(scores), Chunk.tenant_id == DocumentVersion.tenant_id,
               DocumentVersion.status == VersionStatus.READY)
    ).all()
    out = []
    for chunk, ver, doc, tenant in rows:
        if active_only and not ver.is_active:
            continue
        if version_id is not None and ver.id != version_id:
            continue
        label = db.scalar(select(VersionPage.label).where(VersionPage.version_id == ver.id, VersionPage.index == chunk.page_index))
        out.append(Passage(score=round(scores[chunk.id], 4), tenant_id=tenant.id, tenant_name=tenant.name, is_general=tenant.is_global,
                           document_id=doc.id, document_name=doc.name, version_id=ver.id, version=ver.version,
                           page_index=chunk.page_index, page_label=label or f"Page {chunk.page_index}",
                           heading=chunk.heading, text=chunk.text, chunk_id=chunk.id))
    return sorted(out, key=lambda p: p.score, reverse=True)


def _vector(hit) -> list[float] | None:
    v = getattr(hit, "vector", None)
    if isinstance(v, dict):  # named vectors: the collection has one
        v = next(iter(v.values()), None)
    return list(v) if isinstance(v, list | tuple) and v else None


def search_tenants(db: Session, tenant_ids: list[uuid.UUID], question: str, limit: int = 8, min_score: float = 0.0,
                   variety: str = "off") -> list[Passage]:
    """Active documents of the given tenants (the caller decides which tenants, e.g. customer + General).

    `variety` ("off" | "normal" | "high"): with "normal" or "high", more candidates are read and the
    `limit` passages are chosen to be relevant and different from each other (services/diversity),
    so a question asking two things finds passages for both.
    """
    cfg = embeddings.get_config(db)
    indexing.check_model(cfg)  # a question embedded with another model would match nothing sensible
    [vector] = embeddings.embed(cfg, [question])
    pool = diversity.pool_size(limit, variety)
    hits, vectors = [], {}
    for tid in tenant_ids:
        for h in vector_index.search(tid, vector, limit=pool, active_only=True, with_vectors=pool > limit):
            hits.append(h)
            if h.payload and h.payload.get("chunk_id"):
                vectors[str(uuid.UUID(h.payload["chunk_id"]))] = _vector(h)
    passages = [p for p in _passages(db, hits, active_only=True) if p.tenant_id in set(tenant_ids) and p.score >= min_score]
    if pool <= limit:
        return passages[:limit]
    keep = diversity.select([p.score for p in passages], [vectors.get(str(p.chunk_id)) for p in passages], limit, variety)
    return [passages[i] for i in keep]


def search_version(db: Session, version: DocumentVersion, question: str, limit: int = 5) -> list[Passage]:
    """One version, active or not: the preview's "test a question"."""
    cfg = embeddings.get_config(db)
    indexing.check_model(cfg)  # a question embedded with another model would match nothing sensible
    [vector] = embeddings.embed(cfg, [question])
    hits = vector_index.search(version.tenant_id, vector, limit=limit, version_id=version.id)
    # Drop passages with no real similarity, so the admin sees "nothing found" instead of noise.
    return [p for p in _passages(db, hits, active_only=False, version_id=version.id) if p.score > 0.05][:limit]
