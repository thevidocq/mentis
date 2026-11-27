"""Version lifecycle: which version of a document is active, approval, restore, deletion.

Rules
- Only a READY version can be active; exactly one active version per document at most.
- When a version becomes ready: if the tenant requires approval it waits (pending), otherwise
  it becomes active at once, unless a newer version is already active. A failed version never
  replaces the active one.
- Approve activates; reject keeps the previous active version.
- Restore activates an older ready version that is not pending or rejected.
"""

import hashlib
import logging

from sqlalchemy import delete, select, true, update
from sqlalchemy.orm import Session

from app.models import (
    Approval,
    Chunk,
    Document,
    DocumentVersion,
    Tenant,
    VersionPage,
    VersionStatus,
)
from app.models.base import utcnow
from app.services import storage, vector_index

_log = logging.getLogger("mentis.versions")


class VersionError(ValueError):
    pass


def activate(db: Session, version: DocumentVersion) -> None:
    """Make `version` the only active one. The caller commits; the index is updated first so a
    failure there raises before the database changes are committed."""
    if version.status != VersionStatus.READY:
        raise VersionError("Only a processed version can be made active.")
    vector_index.sync_active(version.tenant_id, version.document_id, version.id)
    db.execute(
        update(DocumentVersion)
        .where(DocumentVersion.document_id == version.document_id, DocumentVersion.id != version.id)
        .values(is_active=False)
    )
    version.is_active = True


def on_ready(db: Session, version: DocumentVersion) -> None:
    tenant = db.get(Tenant, version.tenant_id)
    # The General Knowledge Base reaches every customer's answers: its versions always need approval.
    if tenant and (tenant.is_global or (tenant.settings or {}).get("require_approval")):
        version.approval = Approval.PENDING
        version.is_active = False
    else:
        version.approval = Approval.NOT_REQUIRED
        # A version processed late (queued again after a Redis outage, or retried) must not replace
        # a newer version already in use: it stays inactive and can be restored.
        newer_active = db.scalar(select(DocumentVersion.id).where(
            DocumentVersion.document_id == version.document_id, DocumentVersion.is_active.is_(True),
            DocumentVersion.version > version.version))
        if newer_active is None:
            activate(db, version)
        else:
            version.is_active = False


def approve(db: Session, version: DocumentVersion, reviewer_id) -> None:
    if version.approval != Approval.PENDING:
        raise VersionError("This version is not waiting for approval.")
    version.approval = Approval.APPROVED
    version.reviewed_by, version.reviewed_at = reviewer_id, utcnow()
    activate(db, version)


def reject(db: Session, version: DocumentVersion, reviewer_id) -> None:
    if version.approval != Approval.PENDING:
        raise VersionError("This version is not waiting for approval.")
    version.approval = Approval.REJECTED
    version.reviewed_by, version.reviewed_at = reviewer_id, utcnow()
    version.is_active = False
    # A pending version is never active, so the index already marks it inactive; nothing else changes.


def restore(db: Session, version: DocumentVersion) -> None:
    if version.approval in (Approval.PENDING, Approval.REJECTED):
        raise VersionError("Approve this version first.")
    activate(db, version)


def lock_content(db: Session, tenant_id, sha256: str) -> None:
    """Serialise uploads of the same content for one customer until the transaction ends (PostgreSQL),
    so two simultaneous uploads cannot both pass the duplicate check."""
    if db.get_bind().dialect.name != "postgresql":
        return
    from sqlalchemy import text

    key = int.from_bytes(hashlib.sha256(f"{tenant_id}:{sha256}".encode()).digest()[:8], "big", signed=True)
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": key})


def duplicate_message(db: Session, tenant_id, sha256: str, document: Document | None,
                      exclude_version_id=None) -> str | None:
    """Why a file with this content should not be uploaded again for this customer, or None.

    Any version of any document of the customer counts (all file types: the hash is of the bytes),
    except versions that failed to be read or were rejected: uploading those again is allowed.
    """
    rows = db.execute(
        select(DocumentVersion, Document).join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentVersion.tenant_id == tenant_id, DocumentVersion.sha256 == sha256,
               DocumentVersion.status != VersionStatus.FAILED, DocumentVersion.approval != Approval.REJECTED,
               DocumentVersion.id != exclude_version_id if exclude_version_id else true())
        .order_by(DocumentVersion.is_active.desc(), DocumentVersion.version.desc())
    ).all()
    if not rows:
        return None
    same = [(v, d) for v, d in rows if document is not None and d.id == document.id]
    v, d = (same or rows)[0]
    if d.id != getattr(document, "id", None):
        return f"This file is identical to {d.name} v{v.version}: it is already uploaded under that name."
    if v.is_active:
        return "This file is identical to the active version."
    if v.status != VersionStatus.READY:
        return f"This file is identical to v{v.version}, which is still being processed."
    if v.approval == Approval.PENDING:
        return f"This file is identical to v{v.version}, which is waiting for approval."
    return f"This file is identical to v{v.version} of this document: restore it from Versions instead."


class VersionConflict(RuntimeError):
    """Another version of the same document was created at the same moment."""


class StorageDown(RuntimeError):
    """The original could not be stored (MinIO unreachable)."""


def store_version(db: Session, tenant_id, doc: Document, *, filename: str, file_type: str, data: bytes, sha256: str,
                  content_type: str, user_id=None, note: str | None = None) -> DocumentVersion:
    """A new queued version of `doc` with its original stored; the caller queues the processing.

    Raises VersionConflict or StorageDown; on StorageDown the version (and a document left empty)
    is removed again.
    """
    from sqlalchemy.exc import IntegrityError

    version = DocumentVersion(
        document_id=doc.id, tenant_id=tenant_id, version=next_version_number(db, doc), original_filename=filename,
        file_type=file_type, size_bytes=len(data), sha256=sha256, storage_key="", note=note, uploaded_by=user_id,
    )
    try:  # the INSERT happens at flush: a racing upload of the same document fails here
        db.add(version)
        db.flush()
        version.storage_key = storage.original_key(tenant_id, version.id, file_type)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise VersionConflict("Another version of this document is being uploaded. Try again.") from None
    try:
        storage.get_storage().put(version.storage_key, data, content_type)
    except Exception:  # noqa: BLE001 - any storage failure: the version cannot be processed without its file
        db.delete(version)
        db.flush()
        if db.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id == doc.id)) is None:
            db.delete(doc)
        db.commit()
        raise StorageDown("Document storage is not reachable. Try again later.") from None
    return version


def next_version_number(db: Session, document: Document) -> int:
    current = db.scalars(select(DocumentVersion.version).where(DocumentVersion.document_id == document.id)).all()
    return max(current, default=0) + 1


def _delete_version_rows(db: Session, version_ids: list) -> None:
    if not version_ids:
        return
    db.execute(delete(Chunk).where(Chunk.version_id.in_(version_ids)))
    db.execute(delete(VersionPage).where(VersionPage.version_id.in_(version_ids)))
    db.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(version_ids)))


def delete_document(db: Session, document: Document) -> None:
    """The rows go first (committed): answers stop using the document at once. Files and vectors
    are removed next; if MinIO or Qdrant fail, the daily storage sweep removes what is left."""
    from app.services import chat_redaction

    tenant_id, document_id = document.tenant_id, document.id
    version_ids = list(db.scalars(select(DocumentVersion.id).where(DocumentVersion.document_id == document_id)))
    # Its passages leave saved answers too (Sources keep whole passages): in the same commit.
    chat_redaction.redact(db, tenant_id=tenant_id, document_ids=[document_id], document_names=[document.name])
    _delete_version_rows(db, version_ids)
    db.delete(document)
    db.commit()
    _cleanup(lambda: vector_index.delete_document(tenant_id, document_id),
             *[(lambda vid=vid: storage.get_storage().delete_prefix(storage.version_prefix(tenant_id, vid))) for vid in version_ids])


def delete_versions(db: Session, versions: list[DocumentVersion]) -> None:
    """Old versions removed by the retention purge: rows, then files and vectors (best effort)."""
    refs = [(v.tenant_id, v.id) for v in versions]
    _delete_version_rows(db, [vid for _, vid in refs])
    db.commit()
    for tid, vid in refs:
        _cleanup(lambda tid=tid, vid=vid: vector_index.delete_version(tid, vid),
                 lambda tid=tid, vid=vid: storage.get_storage().delete_prefix(storage.version_prefix(tid, vid)))


def delete_tenant_documents(db: Session, tenant_id) -> None:
    """Called when a tenant is deleted, before the caller commits: rows only. The caller then calls
    `cleanup_tenant` (files and vector collection)."""
    version_ids = db.scalars(select(DocumentVersion.id).where(DocumentVersion.tenant_id == tenant_id)).all()
    _delete_version_rows(db, list(version_ids))
    db.execute(delete(Document).where(Document.tenant_id == tenant_id))


def cleanup_tenant(tenant_id) -> None:
    _cleanup(lambda: vector_index.delete_tenant(tenant_id),
             lambda: storage.get_storage().delete_prefix(storage.tenant_prefix(tenant_id)))


def _cleanup(*steps) -> None:
    for step in steps:
        try:
            step()
        except Exception:  # noqa: BLE001 - leftovers are removed by the storage sweep
            _log.warning("storage cleanup deferred to the daily sweep", exc_info=True)
