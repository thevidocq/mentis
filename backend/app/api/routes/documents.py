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
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import client_ip, require_roles
from app.core.ratelimit import user_rate_limit
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
from app.services import access, doc_export, doc_overview, jobs, link_sources, retrieval, storage, versions
from app.services.embeddings import EmbeddingError
from app.services.vector_index import VectorIndexError
from app.services.logs import log_event
from app.services.public_errors import public_message
from app.services.uploads import MIME, UploadError, check_upload, file_type_of, safe_filename

_log = logging.getLogger("mentis.documents")
router = APIRouter(prefix="/tenants/{tenant_id}/documents", tags=["documents"])
admins = require_roles(Role.TENANT_ADMIN)

_MIME = MIME  # content types of the originals (services/uploads)


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


class LinkOut(BaseModel):
    """Documentation read from a link: where, how often, and the last check."""
    url: str
    check: str                       # 6h | 1d | 7d | manual
    checked_at: datetime | None
    next_check_at: datetime | None   # None: checked only on "Check now"
    status: str | None               # new_version | unchanged | error
    error: str | None


class DocumentOut(BaseModel):
    id: uuid.UUID
    name: str
    created_at: datetime
    active: VersionOut | None
    latest: VersionOut
    versions: int
    link: LinkOut | None = None


class DocumentDetail(BaseModel):
    id: uuid.UUID
    name: str
    versions: list[VersionOut]
    link: LinkOut | None = None


class LinkIn(BaseModel):
    url: str = Field(min_length=8, max_length=2000)
    name: str | None = Field(default=None, max_length=200)
    check: str = Field(default=link_sources.DEFAULT_CHECK, pattern="^(6h|1d|7d|manual)$")


class LinkCheckIn(BaseModel):
    check: str = Field(pattern="^(6h|1d|7d|manual)$")


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


def _stored(key: str) -> bytes:
    try:
        return storage.get_storage().get(key)
    except Exception:  # noqa: BLE001 - MinIO down (or the object missing): no stack trace for the user
        _log.warning("could not read %s from storage", key, exc_info=True)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Document storage is not reachable. Try again later.") from None


def _attachment(name: str) -> str:
    """Content-Disposition for a download: an ASCII name plus the exact UTF-8 one."""
    from urllib.parse import quote

    ascii_name = name.encode("ascii", "replace").decode().replace('"', "").replace("?", "_")
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name, safe='')}"


def _link(d: Document) -> LinkOut | None:
    if not d.source_url:
        return None
    every = link_sources.CHECKS.get(d.source_check or "")
    nxt = d.source_checked_at + every if every and d.source_checked_at else None
    return LinkOut(url=d.source_url, check=d.source_check or "manual", checked_at=d.source_checked_at, next_check_at=nxt,
                   status=d.source_status, error=d.source_error)


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
                               latest=_vout(vs[0]), versions=len(vs), link=_link(d)))
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
        checked = await run_in_threadpool(check_upload, file.filename or "", data)  # parsing checks are CPU-bound
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
    if doc is not None and doc.source_url:  # by id or by the same name: its versions come from its link
        raise HTTPException(422, "This document is read from a link: use Check now to read the page again.")
    # Same content already uploaded for this customer (any name, any version, any file type)?
    versions.lock_content(db, tenant.id, checked.sha256)
    duplicate = versions.duplicate_message(db, tenant.id, checked.sha256, doc)
    if duplicate:
        db.rollback()
        log_event(db, "document.upload_refused", level="warning", actor=user, tenant_id=tenant.id,
                  target=checked.filename[:200], ip=client_ip(request), detail={"reason": duplicate, "sha256": checked.sha256})
        raise HTTPException(status.HTTP_409_CONFLICT, duplicate)
    if doc is None:
        doc = Document(tenant_id=tenant.id, name=checked.filename, name_key=name_key, created_by=user.id)
        db.add(doc)
        try:
            db.flush()
        except IntegrityError:  # concurrent upload of the same new name
            db.rollback()
            raise HTTPException(status.HTTP_409_CONFLICT, "This document is being uploaded right now. Try again.") from None

    try:
        version = versions.store_version(db, tenant.id, doc, filename=checked.filename, file_type=checked.file_type, data=data,
                                         sha256=checked.sha256, content_type=_MIME[checked.file_type], user_id=user.id,
                                         note=(note or "").strip() or None)
    except versions.VersionConflict as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    except versions.StorageDown as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None

    log_event(db, "document.uploaded", actor=user, tenant_id=tenant.id, target=checked.filename, ip=client_ip(request),
              detail={"version": version.version, "size": checked.size, "sha256": checked.sha256})
    _enqueue(version)
    db.refresh(version)
    return _vout(version)


@router.post("/link", response_model=VersionOut, status_code=status.HTTP_201_CREATED)
async def add_link(tenant_id: uuid.UUID, body: LinkIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(admins)) -> VersionOut:
    """Documentation from a public link: read now, then checked for changes on its schedule."""
    tenant = _tenant(db, user, tenant_id)
    user_rate_limit(request, user.id, "lookup")
    try:
        doc, version = await run_in_threadpool(link_sources.add, db, tenant, body.url, body.name, body.check, user.id)
    except link_sources.LinkError as e:
        db.rollback()
        log_event(db, "document.link_refused", level="warning", actor=user, tenant_id=tenant.id, target=body.url[:200],
                  ip=client_ip(request), detail={"reason": str(e)})
        raise HTTPException(422, str(e)) from None
    except versions.VersionConflict as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    except versions.StorageDown as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None
    log_event(db, "document.link_added", actor=user, tenant_id=tenant.id, target=doc.name, ip=client_ip(request),
              detail={"url": doc.source_url, "check": doc.source_check, "version": version.version})
    db.refresh(version)
    return _vout(version)


@router.patch("/{document_id}/link", response_model=DocumentDetail)
def set_link_check(tenant_id: uuid.UUID, document_id: uuid.UUID, body: LinkCheckIn, request: Request,
                   db: Session = Depends(get_db), user: User = Depends(admins)) -> DocumentDetail:
    """How often the page is checked for changes."""
    tenant = _tenant(db, user, tenant_id)
    doc = _document(db, tenant, document_id)
    if not doc.source_url:
        raise HTTPException(422, "This document is not read from a link.")
    old, doc.source_check = doc.source_check, body.check
    db.commit()
    log_event(db, "document.link_updated", actor=user, tenant_id=tenant.id, target=doc.name, ip=client_ip(request),
              detail={"check": [old, body.check]})
    return get_document(tenant_id, document_id, db, user)


@router.post("/{document_id}/link/check", response_model=DocumentDetail)
async def check_link_now(tenant_id: uuid.UUID, document_id: uuid.UUID, request: Request,
                         db: Session = Depends(get_db), user: User = Depends(admins)) -> DocumentDetail:
    """Read the page now; a change becomes a new version."""
    tenant = _tenant(db, user, tenant_id)
    doc = _document(db, tenant, document_id)
    if not doc.source_url:
        raise HTTPException(422, "This document is not read from a link.")
    user_rate_limit(request, user.id, "lookup")
    result = await run_in_threadpool(link_sources.sync, db, doc, user.id)
    log_event(db, "document.link_checked", actor=user, tenant_id=tenant.id, target=doc.name, ip=client_ip(request),
              detail={"result": result, "error": doc.source_error})
    return get_document(tenant_id, document_id, db, user)


@router.get("/overview")
def overview(tenant_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(admins)) -> dict:
    """What answers can use today, what needs attention, recent changes (counts only, no content)."""
    return doc_overview.build(db, _tenant(db, user, tenant_id))


@router.get("/export")
def export_all(tenant_id: uuid.UUID, request: Request, format: str = Query(pattern="^(original|md|json)$"),
               db: Session = Depends(get_db), user: User = Depends(admins)) -> StreamingResponse:
    """Every document in use of the customer as a ZIP: originals, Markdown or JSON, plus manifest.json."""
    tenant = _tenant(db, user, tenant_id)
    user_rate_limit(request, user.id, "export")
    try:
        bundle = doc_export.zip_all(db, tenant, format, _stored, get_settings().export_max_mb * 1_000_000)
    except doc_export.ExportError as e:
        raise HTTPException(e.status, str(e)) from None
    log_event(db, "documents.exported", actor=user, tenant_id=tenant.id, target=tenant.name, ip=client_ip(request),
              detail={"format": format, "documents": bundle.count, "not_included": bundle.skipped})
    f = bundle.file
    return StreamingResponse(iter(lambda: f.read(256 * 1024), b""), media_type="application/zip",
                             headers={"Content-Disposition": _attachment(doc_export.zip_name(tenant, format)),
                                      "X-Content-Type-Options": "nosniff"},
                             background=BackgroundTask(f.close))


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(tenant_id: uuid.UUID, document_id: uuid.UUID, db: Session = Depends(get_db), user: User = Depends(admins)) -> DocumentDetail:
    tenant = _tenant(db, user, tenant_id)
    doc = _document(db, tenant, document_id)
    vs = db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == doc.id).order_by(DocumentVersion.version.desc())).all()
    return DocumentDetail(id=doc.id, name=doc.name, versions=[_vout(v) for v in vs], link=_link(doc))


@router.patch("/{document_id}", response_model=DocumentDetail)
def rename_document(tenant_id: uuid.UUID, document_id: uuid.UUID, body: Rename, request: Request,
                    db: Session = Depends(get_db), user: User = Depends(admins)) -> DocumentDetail:
    tenant = _tenant(db, user, tenant_id)
    doc = _document(db, tenant, document_id)
    try:
        name = safe_filename(body.name)
    except UploadError as e:
        raise HTTPException(422, str(e)) from None
    # Keep the file type: versions of one document must all be the same type (.yml and .yaml are one).
    if "." not in name or file_type_of(name) != file_type_of(doc.name):
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
    return Response(_stored(page.image_key), media_type=storage.image_type(page.image_key),
                    headers={"X-Content-Type-Options": "nosniff"})


@router.get("/versions/{version_id}/original")
def download_original(tenant_id: uuid.UUID, version_id: uuid.UUID, request: Request, db: Session = Depends(get_db), user: User = Depends(admins)) -> Response:
    tenant = _tenant(db, user, tenant_id)
    v = _version(db, tenant, version_id)
    data = _stored(v.storage_key)
    log_event(db, "document.downloaded", actor=user, tenant_id=tenant.id, target=v.original_filename, ip=client_ip(request),
              detail={"version": v.version})
    return Response(data, media_type="application/octet-stream", headers={
        "Content-Disposition": _attachment(v.original_filename),
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/versions/{version_id}/export")
def export_version(tenant_id: uuid.UUID, version_id: uuid.UUID, request: Request, format: str = Query(pattern="^(md|json)$"),
                   db: Session = Depends(get_db), user: User = Depends(admins)) -> Response:
    """One version as Markdown or JSON (the text Mentis read; JSON also has the indexed passages)."""
    import json

    tenant = _tenant(db, user, tenant_id)
    v = _version(db, tenant, version_id)
    user_rate_limit(request, user.id, "export")
    try:
        doc_export.readable(v)
    except doc_export.ExportError as e:
        raise HTTPException(e.status, str(e)) from None
    doc = db.get(Document, v.document_id)
    name = f"{doc_export.stem(doc.name)} v{v.version}.{format}"
    if format == "md":
        body, media = doc_export.markdown(db, tenant, doc, v).encode(), "text/markdown; charset=utf-8"
    else:
        body = json.dumps(doc_export.as_json(db, tenant, doc, v), ensure_ascii=False, indent=1).encode()
        media = "application/json"
    log_event(db, "document.exported", actor=user, tenant_id=tenant.id, target=doc.name, ip=client_ip(request),
              detail={"version": v.version, "format": format})
    return Response(body, media_type=media, headers={"Content-Disposition": _attachment(name), "X-Content-Type-Options": "nosniff"})


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
    except VectorIndexError as e:  # Qdrant unreachable: nothing is committed, the active version stays
        db.rollback()
        _log.warning("could not %s version %s: %s", action, v.id, e)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, public_message(e)) from None
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
    # Its content may have been uploaded again meanwhile (failed versions do not count as duplicates).
    doc = db.get(Document, v.document_id)
    duplicate = versions.duplicate_message(db, tenant.id, v.sha256, doc, exclude_version_id=v.id)
    if duplicate:
        raise HTTPException(status.HTTP_409_CONFLICT, duplicate.replace("This file", "This version"))
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
