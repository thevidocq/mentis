"""Retrieval: find the passages that answer a question.

Every hit from Qdrant is re-checked against PostgreSQL (chunk exists, belongs to the expected
tenant and version, version ready and — for answers — active). The database decides; the
index only proposes.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, Document, DocumentVersion, Tenant, VersionPage, VersionStatus
from app.services import embeddings, vector_index


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
                           heading=chunk.heading, text=chunk.text))
    return sorted(out, key=lambda p: p.score, reverse=True)


def search_tenants(db: Session, tenant_ids: list[uuid.UUID], question: str, limit: int = 8, min_score: float = 0.0) -> list[Passage]:
    """Active documents of the given tenants (the caller decides which tenants, e.g. customer + General)."""
    cfg = embeddings.get_config(db)
    [vector] = embeddings.embed(cfg, [question])
    hits = []
    for tid in tenant_ids:
        hits.extend(vector_index.search(tid, vector, limit=limit, active_only=True))
    passages = [p for p in _passages(db, hits, active_only=True) if p.tenant_id in set(tenant_ids) and p.score >= min_score]
    return passages[:limit]


def search_version(db: Session, version: DocumentVersion, question: str, limit: int = 5) -> list[Passage]:
    """One version, active or not: the preview's "test a question"."""
    cfg = embeddings.get_config(db)
    [vector] = embeddings.embed(cfg, [question])
    hits = vector_index.search(version.tenant_id, vector, limit=limit, version_id=version.id)
    # Drop passages with no real similarity, so the admin sees "nothing found" instead of noise.
    return [p for p in _passages(db, hits, active_only=False, version_id=version.id) if p.score > 0.05][:limit]
