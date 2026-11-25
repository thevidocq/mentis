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
from app.services import storage, versions
from app.services.logs import log_event

_log = logging.getLogger("mentis.worker")


def ingest_version(version_id: str) -> None:
    db = next(get_db())
    version = db.get(DocumentVersion, uuid.UUID(version_id))
    if version is None:
        _log.warning("version %s no longer exists", version_id)
        return
    version.status, version.error = VersionStatus.PROCESSING, None
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
        version.stats = stats
        version.status = VersionStatus.READY
        version.processed_at = utcnow()
        versions.on_ready(db, version)
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
    text = str(e) or e.__class__.__name__
    if "password" in text.lower() or "encrypt" in text.lower():
        return "The file is password-protected."
    return text[:500]
