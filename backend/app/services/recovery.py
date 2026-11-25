"""Versions stuck after a worker crash or restart.

- processing for longer than the ingestion timeout: the job died. Mark it failed so the admin can Retry.
- queued for a long time with no job in Redis (Redis lost it): queue it again.
"""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import DocumentVersion, VersionStatus
from app.models.base import utcnow
from app.services import jobs
from app.services.logs import log_event

QUEUED_GRACE = timedelta(minutes=30)
INTERRUPTED = "Processing was interrupted (the worker stopped or timed out). Use Retry."


def recover_stuck_versions(db: Session) -> dict:
    now = utcnow()
    limit = now - timedelta(seconds=get_settings().ingest_timeout_seconds + 600)
    failed = requeued = 0
    for v in db.scalars(select(DocumentVersion).where(DocumentVersion.status == VersionStatus.PROCESSING,
                                                       DocumentVersion.status_at < limit)):
        v.status, v.error = VersionStatus.FAILED, INTERRUPTED
        failed += 1
        log_event(db, "document.interrupted", kind="system", level="error", tenant_id=v.tenant_id,
                  target=v.original_filename, detail={"version": v.version}, commit=False)
    db.commit()
    for v in db.scalars(select(DocumentVersion).where(DocumentVersion.status == VersionStatus.QUEUED,
                                                       DocumentVersion.status_at < now - QUEUED_GRACE)):
        if not jobs.ingest_job_pending(str(v.id)):
            v.status_at = now
            db.commit()
            jobs.enqueue_ingest(str(v.id))
            requeued += 1
    return {"failed": failed, "requeued": requeued}
