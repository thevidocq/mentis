"""Version lifecycle: which version of a document is active, approval, restore, deletion.

Rules
- Only a READY version can be active; exactly one active version per document at most.
- When a version becomes ready: if the tenant requires approval it waits (pending), otherwise
  it becomes active at once, unless a newer version is already active. A failed version never
  replaces the active one.
- Approve activates; reject keeps the previous active version.
- Restore activates an older ready version that is not pending or rejected.
"""

from sqlalchemy import delete, select, update
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
    versions = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id)).all()
    vector_index.delete_document(document.tenant_id, document.id)
    store = storage.get_storage()
    for v in versions:
        store.delete_prefix(storage.version_prefix(v.tenant_id, v.id))
    _delete_version_rows(db, [v.id for v in versions])
    db.delete(document)
    db.commit()


def delete_tenant_documents(db: Session, tenant_id) -> None:
    """Called when a tenant is deleted: rows and stored files."""
    version_ids = db.scalars(select(DocumentVersion.id).where(DocumentVersion.tenant_id == tenant_id)).all()
    _delete_version_rows(db, list(version_ids))
    db.execute(delete(Document).where(Document.tenant_id == tenant_id))
    vector_index.delete_tenant(tenant_id)
    storage.get_storage().delete_prefix(storage.tenant_prefix(tenant_id))
