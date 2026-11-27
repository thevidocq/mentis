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
from app.services.public_errors import public_message

_log = logging.getLogger("mentis.worker")


class StorageUnavailable(RuntimeError):
    """MinIO failed while processing; the message is safe to show to tenant admins."""


def ingest_version(version_id: str) -> None:
    db = next(get_db())
    version = db.get(DocumentVersion, uuid.UUID(version_id))
    if version is None:
        _log.warning("version %s no longer exists", version_id)
        return
    if version.status != VersionStatus.QUEUED:
        # A duplicate job (e.g. queued again by recovery just as the first one finished): processing
        # a ready version again would reset its approval and take it out of answers meanwhile.
        _log.warning("version %s is %s, not queued: job skipped", version_id, version.status)
        db.close()
        return
    version.status, version.error, version.status_at = VersionStatus.PROCESSING, None, utcnow()
    db.commit()
    prefix = storage.version_prefix(version.tenant_id, version.id)
    tenant_id = version.tenant_id

    store = storage.get_storage()
    try:
        try:
            data = store.get(version.storage_key)
        except Exception as e:  # noqa: BLE001 - the raw error carries the storage address and key
            raise StorageUnavailable("The stored file could not be read (document storage not reachable). Use Retry.") from e
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
                try:
                    store.put(image_key, page.image, "image/webp")
                except Exception as e:  # noqa: BLE001 - as above
                    raise StorageUnavailable("Page images could not be saved (document storage not reachable). Use Retry.") from e
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
        done = {"version": version.version, "pages": stats["pages"], "ocr_pages": stats["ocr_pages"], "approval": version.approval}
        done_target = version.original_filename
    except Exception as e:  # noqa: BLE001 - any failure marks the version failed; the active one is untouched
        db.rollback()
        version = db.get(DocumentVersion, uuid.UUID(version_id))
        if version is None:
            # Deleted while processing: drop page images and index points written meanwhile.
            storage.get_storage().delete_prefix(prefix)
            try:
                vector_index.delete_version(tenant_id, version_id)
            except Exception:  # noqa: BLE001 - search re-checks the database anyway
                _log.warning("could not clean index points for deleted version %s", version_id)
            db.close()
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
        try:
            log_event(db, "document.failed", kind="system", level="error", tenant_id=version.tenant_id,
                      target=version.original_filename,
                      detail={"version": version.version, "error": version.error, "cause": str(e.__cause__ or e)[:500]})
        finally:
            db.close()
        return
    # Logged after the commit and outside the try: a failure to write the log must never turn a
    # version already in use into a failed one (its index flags were already switched).
    try:
        log_event(db, "document.processed", kind="system", tenant_id=tenant_id, target=done_target, detail=done)
    except Exception:  # noqa: BLE001 - the version is processed; only the audit line is missing
        db.rollback()
        _log.exception("could not log the processing of version %s", version_id)
    finally:
        db.close()


def _user_message(e: Exception) -> str:
    # Shown to tenant admins: no service address or raw reply (the log event keeps the cause).
    if isinstance(e, embeddings.EmbeddingError | vector_index.VectorIndexError):
        return f"Indexing failed: {public_message(e)}"
    text = str(e) or e.__class__.__name__
    if "password" in text.lower() or "encrypt" in text.lower():
        return "The file is password-protected."
    return text[:500]


REINDEX_STATE = "reindex"
REPROCESS_STATE = "reprocess"


def _state(db, key: str, **value) -> None:
    from app.models import PlatformSetting

    row = db.get(PlatformSetting, key)
    if row is None:
        db.add(PlatformSetting(key=key, value=value))
    else:
        row.value = value
    db.commit()


def reindex_all() -> None:
    """Rebuild every tenant's collection from stored chunks (after an embedding model change).

    While it runs, and if it fails after the index was cleared, answers are paused with a clear
    message (indexing.check_ready): never an answer from a half-built index. The new model is
    recorded only when every version is indexed; a version that fails is tried once more, and any
    still failing make the rebuild fail with their names. Versions that become ready meanwhile are
    indexed in a last pass."""
    from sqlalchemy import select

    from app.models import Document, Tenant

    db = next(get_db())
    state = lambda **v: _state(db, REINDEX_STATE, **v)  # noqa: E731
    cleared = False
    try:
        cfg = embeddings.get_config(db)
        # Probe the model first: it fails fast if the service is down (nothing is touched then).
        [probe] = embeddings.embed(cfg, ["Mentis"])
        cfg.update(indexed_model=cfg["model"], indexed_dim=len(probe))  # this run writes with the new model
        ready = db.scalars(select(DocumentVersion).where(DocumentVersion.status == VersionStatus.READY)).all()
        done_ids = set()
        state(status="running", done=0, total=len(ready), error=None, blocking=True)
        for tenant_id in {t for (t,) in db.execute(select(Tenant.id))}:
            vector_index.delete_tenant(tenant_id)
        cleared = True
        failed: list[str] = []

        def one(v) -> None:
            for attempt in (1, 2):
                try:
                    indexing.index_version(db, v, cfg, active=v.is_active)
                    done_ids.add(v.id)
                    return
                except Exception:  # noqa: BLE001 - retried once, then reported by name
                    db.rollback()
                    if attempt == 2:
                        doc = db.get(Document, v.document_id)
                        failed.append(f"{doc.name if doc else v.original_filename} v{v.version}")
                        _log.exception("reindex: version %s failed", v.id)

        for i, v in enumerate(ready, start=1):
            one(v)
            if i % 10 == 0 or i == len(ready):
                state(status="running", done=i, total=len(ready), error=None, blocking=True)
        # Versions that became ready while the index was cleared and rebuilt.
        for v in db.scalars(select(DocumentVersion).where(DocumentVersion.status == VersionStatus.READY)).all():
            if v.id not in done_ids and v.id not in {r.id for r in ready}:
                one(v)
        if failed:
            raise RuntimeError(f"{len(failed)} version(s) could not be indexed: {', '.join(failed[:10])}")
        embeddings.record_index(db, cfg["model"], len(probe))
        state(status="done", done=len(ready), total=len(ready), error=None, finished_at=utcnow().isoformat())
        log_event(db, "index.reindexed", kind="system", detail={"versions": len(ready), "model": cfg["model"]})
    except Exception as e:  # noqa: BLE001 - report the failure on the admin page
        db.rollback()
        state(status="failed", error=str(e)[:500], blocking=cleared)
        _log.exception("reindex failed")
        log_event(db, "index.reindex_failed", kind="system", level="error", detail={"error": str(e)[:300]})
    finally:
        db.close()


def reprocess_all() -> None:
    """Read every version in use or waiting again from its original file with the current readers,
    and swap its pages, chunks and index points in place: approval and activation do not change,
    and the version stays in answers throughout (new points are written before the old ones go).
    A version whose file can no longer be read keeps its current reading and is reported."""
    from sqlalchemy import select

    from app.models import Document

    db = next(get_db())
    state = lambda **v: _state(db, REPROCESS_STATE, **v)  # noqa: E731
    try:
        cfg = embeddings.get_config(db)
        indexing.check_model(cfg)
        todo = [v.id for v in db.scalars(select(DocumentVersion).where(DocumentVersion.status == VersionStatus.READY))]
        state(status="running", done=0, total=len(todo), error=None)
        failed: list[str] = []
        for i, vid in enumerate(todo, start=1):
            try:
                _reprocess_version(db, vid, cfg)
            except Exception:  # noqa: BLE001 - this version keeps its current reading
                db.rollback()
                v = db.get(DocumentVersion, vid)
                if v is not None:
                    doc = db.get(Document, v.document_id)
                    failed.append(f"{doc.name if doc else v.original_filename} v{v.version}")
                _log.exception("reprocess: version %s failed", vid)
            if i % 5 == 0 or i == len(todo):
                state(status="running", done=i, total=len(todo), error=None)
        error = f"{len(failed)} version(s) kept their previous reading: {', '.join(failed[:10])}" if failed else None
        state(status="done", done=len(todo), total=len(todo), error=error, finished_at=utcnow().isoformat())
        log_event(db, "documents.reprocessed", kind="system", level="warning" if failed else "info",
                  detail={"versions": len(todo), "failed": failed[:50]})
    except Exception as e:  # noqa: BLE001 - report the failure on the admin page
        db.rollback()
        state(status="failed", error=str(e)[:500])
        _log.exception("reprocess failed")
    finally:
        db.close()


def _reprocess_version(db, version_id, cfg: dict) -> None:
    from sqlalchemy import select

    version = db.get(DocumentVersion, version_id)
    if version is None or version.status != VersionStatus.READY:
        return
    store = storage.get_storage()
    s = get_settings()
    result = parse(store.get(version.storage_key), version.file_type, ParseLimits(max_pages=s.max_pages),
                   parser=os.getenv("MENTIS_PARSER", "standard"))
    if not result.pages or result.stats()["chars"] == 0:
        raise ValueError("no readable text")
    old_chunks = [c for (c,) in db.execute(select(Chunk.id).where(Chunk.version_id == version.id))]
    db.execute(delete(VersionPage).where(VersionPage.version_id == version.id))
    for page in result.pages:
        image_key = None
        if page.image:
            image_key = storage.page_image_key(version.tenant_id, version.id, page.index)
            store.put(image_key, page.image, "image/webp")
        db.add(VersionPage(version_id=version.id, tenant_id=version.tenant_id, index=page.index, kind=page.kind,
                           label=page.label, text=page.text, method=page.method, ocr_confidence=page.ocr_confidence,
                           tables=page.tables, image_key=image_key, flags=page.flags))
    new = [Chunk(version_id=version.id, tenant_id=version.tenant_id, ordinal=i, page_index=c.page_index,
                 heading=c.heading, text=c.text, chars=len(c.text)) for i, c in enumerate(chunk_pages(result.pages))]
    db.add_all(new)
    db.flush()
    vectors = embeddings.embed(cfg, [indexing.chunk_text_for_embedding(c) for c in new])
    vector_index.upsert_chunks(version.tenant_id, version.document_id, version.id, version.is_active,
                               [(c.id, v) for c, v in zip(new, vectors, strict=True)])
    try:
        db.execute(delete(Chunk).where(Chunk.id.in_(old_chunks)))
        stats = result.stats()
        stats["chunks"] = len(new)
        version.stats = stats
        db.commit()
    except Exception:
        db.rollback()
        vector_index.delete_points(version.tenant_id, [c.id for c in new])
        raise
    vector_index.delete_points(version.tenant_id, old_chunks)
