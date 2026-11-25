"""Ingestion job: parse a stored version, save pages, images and chunks, then apply activation rules."""

import logging
import os
import uuid

from sqlalchemy import delete

from app.core.config import get_settings
from app.core.db import get_db
from app.ingestion import ParseLimits, parse
from app.ingestion.chunking import chunk_pages
from app.models import Chunk, DocumentVersion, VersionPage, VersionStatus
from app.models.base import utcnow
from app.services import embeddings, indexing, storage, vector_index, versions
from app.services.logs import log_event

_log = logging.getLogger("mentis.worker")


def ingest_version(version_id: str) -> None:
    db = next(get_db())
    version = db.get(DocumentVersion, uuid.UUID(version_id))
    if version is None:
        _log.warning("version %s no longer exists", version_id)
        return
    version.status, version.error, version.status_at = VersionStatus.PROCESSING, None, utcnow()
    db.commit()
    prefix = storage.version_prefix(version.tenant_id, version.id)

    store = storage.get_storage()
    try:
        data = store.get(version.storage_key)
        s = get_settings()
        result = parse(data, version.file_type, ParseLimits(max_pages=s.max_pages), parser=os.getenv("MENTIS_PARSER", "standard"))
        if not result.pages:
            raise ValueError("No content could be read from this file.")

        # Re-processing replaces previous output.
        db.execute(delete(Chunk).where(Chunk.version_id == version.id))
        db.execute(delete(VersionPage).where(VersionPage.version_id == version.id))
        for page in result.pages:
            image_key = None
            if page.image:
                image_key = storage.page_image_key(version.tenant_id, version.id, page.index)
                store.put(image_key, page.image, "image/png")
            db.add(VersionPage(
                version_id=version.id, tenant_id=version.tenant_id, index=page.index, kind=page.kind,
                label=page.label, text=page.text, method=page.method, ocr_confidence=page.ocr_confidence,
                tables=page.tables, image_key=image_key, flags=page.flags,
            ))
        for i, c in enumerate(chunk_pages(result.pages)):
            db.add(Chunk(version_id=version.id, tenant_id=version.tenant_id, ordinal=i, page_index=c.page_index,
                         heading=c.heading, text=c.text, chars=len(c.text)))

        stats = result.stats()
        if stats["chars"] == 0:
            raise ValueError("The file contains no readable text.")
        db.flush()

        # Index as the last step: a version that cannot be indexed fails and never replaces the active one.
        cfg = embeddings.get_config(db)
        indexing.check_model(cfg)
        stats["chunks"] = indexing.index_version(db, version, cfg, active=False)

        version.stats = stats
        version.status = VersionStatus.READY
        version.processed_at = utcnow()
        versions.on_ready(db, version)  # flips the index flag too if the version becomes active
        db.commit()
        log_event(db, "document.processed", kind="system", tenant_id=version.tenant_id, target=version.original_filename,
                  detail={"version": version.version, "pages": stats["pages"], "ocr_pages": stats["ocr_pages"],
                          "approval": version.approval})
    except Exception as e:  # noqa: BLE001 - any failure marks the version failed; the active one is untouched
        db.rollback()
        version = db.get(DocumentVersion, uuid.UUID(version_id))
        if version is None:
            # Deleted while processing: drop any page images written meanwhile.
            storage.get_storage().delete_prefix(prefix)
            return
        try:
            vector_index.delete_version(version.tenant_id, version.id)
        except Exception:  # noqa: BLE001 - index unreachable: search re-checks the database anyway
            _log.warning("could not clean index points for failed version %s", version_id)
        version.status, version.is_active = VersionStatus.FAILED, False
        version.error = _user_message(e)
        version.processed_at = utcnow()
        db.commit()
        _log.exception("ingestion failed for version %s", version_id)
        log_event(db, "document.failed", kind="system", level="error", tenant_id=version.tenant_id,
                  target=version.original_filename, detail={"version": version.version, "error": version.error})
    finally:
        db.close()


def _user_message(e: Exception) -> str:
    if isinstance(e, embeddings.EmbeddingError):
        return f"Indexing failed: {e}"
    if isinstance(e, vector_index.VectorIndexError):
        return f"Indexing failed: {e}"
    text = str(e) or e.__class__.__name__
    if "password" in text.lower() or "encrypt" in text.lower():
        return "The file is password-protected."
    return text[:500]


REINDEX_STATE = "reindex"


def reindex_all() -> None:
    """Rebuild every tenant's collection from stored chunks (after an embedding model change)."""
    from sqlalchemy import select

    from app.models import PlatformSetting, Tenant

    db = next(get_db())

    def state(**value):
        row = db.get(PlatformSetting, REINDEX_STATE)
        if row is None:
            db.add(PlatformSetting(key=REINDEX_STATE, value=value))
        else:
            row.value = value
        db.commit()

    try:
        cfg = embeddings.get_config(db)
        cfg.update(indexed_model=None, indexed_dim=None)  # force recording the new model
        ready = db.scalars(select(DocumentVersion).where(DocumentVersion.status == VersionStatus.READY)).all()
        state(status="running", done=0, total=len(ready), error=None)
        for tenant_id in {t for (t,) in db.execute(select(Tenant.id))}:
            vector_index.delete_tenant(tenant_id)
        for i, v in enumerate(ready, start=1):
            indexing.index_version(db, v, cfg, active=v.is_active)
            if i % 10 == 0 or i == len(ready):
                state(status="running", done=i, total=len(ready), error=None)
        state(status="done", done=len(ready), total=len(ready), error=None, finished_at=utcnow().isoformat())
        log_event(db, "index.reindexed", kind="system", detail={"versions": len(ready), "model": cfg["model"]})
    except Exception as e:  # noqa: BLE001 - report the failure on the admin page
        db.rollback()
        state(status="failed", error=str(e)[:500])
        _log.exception("reindex failed")
        log_event(db, "index.reindex_failed", kind="system", level="error", detail={"error": str(e)[:300]})
    finally:
        db.close()
