"""Embedding chunks and writing them to the tenant's Qdrant collection."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chunk, DocumentVersion
from app.services import embeddings, vector_index


def chunk_text_for_embedding(chunk: Chunk) -> str:
    # The section path gives every chunk its context ("Ransomware > Tier 2 > Contacts").
    return f"{chunk.heading}\n\n{chunk.text}" if chunk.heading else chunk.text


def check_model(cfg: dict) -> None:
    if cfg["indexed_model"] and cfg["indexed_model"] != cfg["model"]:
        raise embeddings.EmbeddingModelChanged(
            f"The embedding model changed ({cfg['indexed_model']} → {cfg['model']}). "
            "A super-admin must run Reindex in Embedding and Qdrant.", public=True,
        )


def check_ready(db: Session, cfg: dict) -> None:
    """Answers only from a complete index: not while it is rebuilt, nor after a rebuild that failed
    once the index was cleared (some documents would be missing without notice)."""
    from app.models import PlatformSetting

    check_model(cfg)
    row = db.get(PlatformSetting, "reindex")
    state = (row.value or {}) if row else {}
    if state.get("status") in ("queued", "running") and state.get("blocking", state.get("status") == "running"):
        done, total = state.get("done") or 0, state.get("total") or 0
        raise embeddings.EmbeddingModelChanged(
            f"The search index is being rebuilt ({done} of {total} documents): answers resume when it finishes.", public=True)
    if state.get("status") == "failed" and state.get("blocking"):
        raise embeddings.EmbeddingModelChanged(
            "Rebuilding the search index failed, so some documents are missing from it: a super-admin must run "
            "Reindex again in Embedding and Qdrant.", public=True)


def index_version(db: Session, version: DocumentVersion, cfg: dict, active: bool) -> int:
    """(Re)write a version's points. Returns the number of chunks indexed."""
    chunks = db.scalars(select(Chunk).where(Chunk.version_id == version.id).order_by(Chunk.ordinal)).all()
    vector_index.delete_version(version.tenant_id, version.id)
    if not chunks:
        return 0
    vectors = embeddings.embed(cfg, [chunk_text_for_embedding(c) for c in chunks])
    vector_index.upsert_chunks(version.tenant_id, version.document_id, version.id, active,
                               [(c.id, v) for c, v in zip(chunks, vectors, strict=True)])
    if cfg["indexed_model"] != cfg["model"] or not cfg["indexed_dim"]:
        embeddings.record_index(db, cfg["model"], len(vectors[0]))
        cfg.update(indexed_model=cfg["model"], indexed_dim=len(vectors[0]))
    return len(chunks)
