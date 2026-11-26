"""Documents of a tenant: upload, versions, preview, approval, restore, rename, delete.

Access: tenant admins, for the tenants they administer (General included when they have it).
Super-admins manage the platform and have no access to documents.
Every query filters by the tenant resolved here, never by IDs alone.
"""

import logging
import uuid
from datetime import datetime

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.core.config import get_settings
from app.core.db import get_db
from app.models import (
    Document,
    DocumentVersion,
    Role,
    Tenant,
    User,
    VersionPage,
    VersionStatus,
)
from app.models.base import utcnow
from app.services import access, doc_overview, jobs, retrieval, storage, versions
from app.services.embeddings import EmbeddingError
from app.services.vector_index import VectorIndexError
from app.services.logs import log_event
from app.services.public_errors import public_message
from app.services.uploads import UploadError, check_upload, safe_filename

_log = logging.getLogger("mentis.documents")
router = APIRouter(prefix="/tenants/{tenant_id}/documents", tags=["documents"])
admins = require_roles(Role.TENANT_ADMIN)

_MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


# --- Schemas -------------------------------------------------------------------

class VersionOut(BaseModel):
    id: uuid.UUID
    version: int
    original_filename: str
    file_type: str
    size_bytes: int
    status: str
    approval: str
    is_active: bool
    note: str | None
    error: str | None
    stats: dict
    uploaded_at: datetime
    processed_at: datetime | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    active: VersionOut | None
    latest: VersionOut
    versions: int


class DocumentDetail(BaseModel):
    id: uuid.UUID
    name: str
    versions: list[VersionOut]


class PageOut(BaseModel):
    index: int
    kind: str
    label: str
    text: str
    method: str
    ocr_confidence: float | None
    tables: int
    has_image: bool
    flags: list[str]


class SearchIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)


class PassageOut(BaseModel):
    score: float
    page_index: int
    page_label: str
    heading: str | None
    text: str


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=200)


# --- Access helpers --------------------------------------------------------------

def _tenant(db: Session, user: User, tenant_id: uuid.UUID) -> Tenant:
    tenant = db.get(Tenant, tenant_id)
    allowed = tenant is not None and (
        access.administers(db, user, tenant_id)
    )
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found.")
    return tenant


def _document(db: Session, tenant: Tenant, document_id: uuid.UUID) -> Document:
    doc = db.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == tenant.id))
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
    return doc


def _version(db: Session, tenant: Tenant, version_id: uuid.UUID) -> DocumentVersion:
    v = db.scalar(select(DocumentVersion).where(DocumentVersion.id == version_id, DocumentVersion.tenant_id == tenant.id))
    if v is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found.")
    return v


def _enqueue(v: DocumentVersion) -> None:
    """Queue processing. If Redis is down the version stays Queued: the worker's recovery queues it again."""
    try:
        jobs.enqueue_ingest(str(v.id))
    except Exception:  # noqa: BLE001 - the upload itself succeeded
        _log.warning("could not queue version %s; recovery will retry", v.id)


def _vout(v: DocumentVersion) -> VersionOut:
    return VersionOut.model_validate(v, from_attributes=True)


# --- Documents -------------------------------------------------------------------

@router.get("", response_model=list[DocumentOut])
def list_documents(tenant_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(admins)) -> list[DocumentOut]:
    tenant = _tenant(db, user, tenant_id)
    docs = db.scalars(select(Document).where(Document.tenant_id == tenant.id).order_by(Document.name)).all()
    out = []
    for d in docs:
        vs = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == d.id).order_by(DocumentVersion.version.desc())).all()
        if not vs:
            continue
        active = next((v for v in vs if v.is_active), None)
        out.append(DocumentOut(id=d.id, name=d.name, created_at=d.created_at, active=_vout(active) if active else None,
                               latest=_vout(vs[0]), versions=len(vs)))
    return out


@router.post("", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
async def upload(
    tenant_id: uuid.UUID,
    request: Request,
    file: UploadFile = File(...),
    note: str | None = Form(default=None, max_length=500),
    document_id: uuid.UUID | None = Form(default=None),  # "New version" of this document, whatever the file name
    db: Session = Depends(get_db),
    user: User = Depends(admins),
) -> VersionOut:
    tenant = _tenant(db, user, tenant_id)
    limit = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(limit + 1)
    try:
        checked = check_upload(file.filename or "", data)
    except UploadError as e:
        log_event(db, "document.upload_refused", level="warning", actor=user, tenant_id=tenant.id,
                  target=(file.filename or "")[:200], ip=client_ip(request), detail={"reason": str(e)})
        raise HTTPException(422, str(e)) from None

    name_key = checked.filename.lower()
    if document_id is not None:
        doc = db.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == tenant.id))
        if doc is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found.")
        latest = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id)
                           .order_by(DocumentVersion.version.desc()).limit(1))
        if latest is not None and latest.file_type != checked.file_type:
            raise HTTPException(422, f"A new version must be a {latest.file_type.upper()} file, like the previous ones.")
    else:
        doc = db.scalar(select(Document).where(Document.tenant_id == tenant.id, Document.name_key == name_key))
    if doc is None:
        doc = Document(tenant_id=tenant.id, name=checked.filename, name_key=name_key, created_by=user.id)
        db.add(doc)
        try:
            db.flush()
        except IntegrityError:  # concurrent upload of the same new name
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "This document is being uploaded right now. Try again.") from None
    else:
        active = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == doc.id, DocumentVersion.is_active.is_(True)))
        if active is not None and active.sha256 == checked.sha256:
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "This file is identical to the active version.")

    version = DocumentVersion(
        document_id=doc.id, tenant_id=tenant.id, version=versions.next_version_number(db, doc),
        original_filename=checked.filename, file_type=checked.file_type, size_bytes=checked.size,
        sha256=checked.sha256, storage_key="", note=(note or "").strip() or None, uploaded_by=user.id,
    )
    db.add(version)
    db.flush()
    version.storage_key = storage.original_key(tenant.id, version.id, checked.file_type)
    try:
        db.commit()
    except IntegrityError:  # two uploads of the same document at the same moment
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Another version of this document is being uploaded. Try again.") from None
    try:
        storage.get_storage().put(version.storage_key, data, _MIME[checked.file_type])
    except Exception:
        # Without the stored file the version cannot be processed: remove it (and a document left empty).
        db.delete(version)
        db.flush()
        if db.scalar(select(DocumentVersion.id).where(DocumentVersion.document_id == doc.id)) is None:
            db.delete(doc)
        db.commit()
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Document storage is not reachable. Try again later.") from None

    log_event(db, "document.uploaded", actor=user, tenant_id=tenant.id, target=checked.filename, ip=client_ip(request),
              detail={"version": version.version, "size": checked.size, "sha256": checked.sha256})
    _enqueue(version)
    db.refresh(version)
    return _vout(version)


@router.get("/overview")
def overview(tenant_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(admins)) -> dict:
    """What answers can use today, what needs attention, recent changes (counts only, no content)."""
    return doc_overview.build(db, _tenant(db, user, tenant_id))


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(tenant_id: uuid.UUID, document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(admins)) -> DocumentDetail:
    tenant = _tenant(db, user, tenant_id)
    doc = _document(db, tenant, document_id)
    vs = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == doc.id).order_by(DocumentVersion.version.desc())).all()
    return DocumentDetail(id=doc.id, name=doc.name, versions=[_vout(v) for v in vs])


@router.patch("/{document_id}", response_model=DocumentDetail)
def rename_document(tenant_id: uuid.UUID, document_id: uuid.UUID, body: Rename, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(admins)) -> DocumentDetail:
    tenant = _tenant(db, user, tenant_id)
    doc = _document(db, tenant, document_id)
    try:
        name = safe_filename(body.name)
    except UploadError as e:
        raise HTTPException(422, str(e)) from None
    # Keep the extension: versions of one document must all be the same file type.
    if name.rsplit(".", 1)[-1].lower() != doc.name.rsplit(".", 1)[-1].lower():
        raise HTTPException(422, f"Keep the .{doc.name.rsplit('.', 1)[-1].lower()} extension.")
    old = doc.name
    doc.name, doc.name_key = name, name.lower()
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Another document already has this name.") from None
    log_event(db, "document.renamed", actor=user, tenant_id=tenant.id, target=name, ip=client_ip(request), detail={"from": old})
    return get_document(tenant_id, document_id, db, user)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(tenant_id: uuid.UUID, document_id: uuid.UUID, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(admins)) -> None:
    tenant = _tenant(db, user, tenant_id)
    doc = _document(db, tenant, document_id)
    name = doc.name
    versions.delete_document(db, doc)
    log_event(db, "document.deleted", level="warning", actor=user, tenant_id=tenant.id, target=name, ip=client_ip(request))


# --- Versions ----------------------------------------------------------------------

@router.get("/versions/{version_id}", response_model=VersionOut)
def get_version(tenant_id: uuid.UUID, version_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(admins)) -> VersionOut:
    return _vout(_version(db, _tenant(db, user, tenant_id), version_id))


@router.get("/versions/{version_id}/pages", response_model=list[PageOut])
def version_pages(tenant_id: uuid.UUID, version_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(admins)) -> list[PageOut]:
    tenant = _tenant(db, user, tenant_id)
    v = _version(db, tenant, version_id)
    pages = db.scalars(select(VersionPage).where(VersionPage.version_id == v.id, VersionPage.tenant_id == tenant.id).order_by(VersionPage.index)).all()
    return [PageOut(index=p.index, kind=p.kind, label=p.label, text=p.text, method=p.method, ocr_confidence=p.ocr_confidence,
                    tables=p.tables, has_image=bool(p.image_key), flags=p.flags or []) for p in pages]


@router.get("/versions/{version_id}/pages/{index}/image")
def page_image(tenant_id: uuid.UUID, version_id: uuid.UUID, index: int, db: Session = Depends(get_db), user: User = Depends(admins)) -> Response:
    tenant = _tenant(db, user, tenant_id)
    v = _version(db, tenant, version_id)
    page = db.scalar(select(VersionPage).where(VersionPage.version_id == v.id, VersionPage.index == index))
    if page is None or not page.image_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No image for this page.")
    return Response(storage.get_storage().get(page.image_key), media_type="image/png",
                    headers={"X-Content-Type-Options": "nosniff"})


@router.get("/versions/{version_id}/original")
def download_original(tenant_id: uuid.UUID, version_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(admins)) -> Response:
    tenant = _tenant(db, user, tenant_id)
    v = _version(db, tenant, version_id)
    data = storage.get_storage().get(v.storage_key)
    ascii_name = v.original_filename.encode("ascii", "replace").decode().replace('"', "").replace("?", "_")
    log_event(db, "document.downloaded", actor=user, tenant_id=tenant.id, target=v.original_filename, ip=client_ip(request),
              detail={"version": v.version})
    return Response(data, media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{ascii_name}"',
        "X-Content-Type-Options": "nosniff",
    })


def _transition(action: str, tenant_id: uuid.UUID, version_id: uuid.UUID, request: Request, db: Session, user: User) -> VersionOut:
    tenant = _tenant(db, user, tenant_id)
    v = _version(db, tenant, version_id)
    try:
        if action == "approve":
            versions.approve(db, v, user.id)
        elif action == "reject":
            versions.reject(db, v, user.id)
        elif action == "restore":
            versions.restore(db, v)
    except versions.VersionError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    db.commit()
    log_event(db, f"document.version_{action}d" if action != "reject" else "document.version_rejected", actor=user,
              tenant_id=tenant.id, target=v.original_filename, ip=client_ip(request), detail={"version": v.version})
    return _vout(v)


@router.post("/versions/{version_id}/approve", response_model=VersionOut)
def approve_version(tenant_id: uuid.UUID, version_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(admins)) -> VersionOut:
    return _transition("approve", tenant_id, version_id, request, db, user)


@router.post("/versions/{version_id}/reject", response_model=VersionOut)
def reject_version(tenant_id: uuid.UUID, version_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(admins)) -> VersionOut:
    return _transition("reject", tenant_id, version_id, request, db, user)


@router.post("/versions/{version_id}/restore", response_model=VersionOut)
def restore_version(tenant_id: uuid.UUID, version_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(admins)) -> VersionOut:
    return _transition("restore", tenant_id, version_id, request, db, user)


@router.post("/versions/{version_id}/retry", response_model=VersionOut)
def retry_version(tenant_id: uuid.UUID, version_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(admins)) -> VersionOut:
    tenant = _tenant(db, user, tenant_id)
    v = _version(db, tenant, version_id)
    if v.status != VersionStatus.FAILED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Only a failed version can be processed again.")
    v.status, v.error, v.status_at = VersionStatus.QUEUED, None, utcnow()
    db.commit()
    log_event(db, "document.retry", actor=user, tenant_id=tenant.id, target=v.original_filename, ip=client_ip(request), detail={"version": v.version})
    _enqueue(v)
    db.refresh(v)
    return _vout(v)


@router.post("/versions/{version_id}/search", response_model=list[PassageOut])
def test_question(tenant_id: uuid.UUID, version_id: uuid.UUID, body: SearchIn, request: Request,
                  db: Session = Depends(get_db), user: User = Depends(admins)) -> list[PassageOut]:
    """Preview's "test a question": the passages of this version that best match the question."""
    tenant = _tenant(db, user, tenant_id)
    v = _version(db, tenant, version_id)
    if v.status != VersionStatus.READY:
        raise HTTPException(status.HTTP_409_CONFLICT, "This version is not processed yet.")
    try:
        found = retrieval.search_version(db, v, body.question)
    except (EmbeddingError, VectorIndexError) as e:
        log_event(db, "document.test_question_failed", kind="system", level="error", actor=user, tenant_id=tenant.id,
                  target=v.original_filename, detail={"error": str(e)[:300]})
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, public_message(e)) from None
    log_event(db, "document.test_question", actor=user, tenant_id=tenant.id, target=v.original_filename,
              ip=client_ip(request), detail={"version": v.version})  # the question itself is not logged
    return [PassageOut(score=p.score, page_index=p.page_index, page_label=p.page_label, heading=p.heading, text=p.text) for p in found]
