"""Documents for use elsewhere: one version, or every document in use of a customer as a ZIP.

Formats:
- original: the uploaded file;
- md: the text Mentis read, as Markdown, one section per page / slide / sheet, with a header
  (customer, document, version, file, upload date, SHA-256);
- json: the same plus the passages as indexed (page, section, text), for another RAG or a script
  ("format": "mentis-document/1").
"""

import json
import re
import tempfile
import zipfile
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import __version__
from app.models import Chunk, Document, DocumentVersion, Tenant, VersionPage, VersionStatus
from app.models.base import utcnow
from app.services.setup import GENERAL_NAME

FORMATS = ("original", "md", "json")
JSON_FORMAT = "mentis-document/1"


class ExportError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _owner(tenant: Tenant) -> str:
    return GENERAL_NAME if tenant.is_global else tenant.name


def stem(name: str) -> str:
    """File name without extension, safe in a ZIP and on Windows."""
    base = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name or "document")
    base = re.sub(r'[\x00-\x1f<>:"/\\|?*]+', "_", base).strip(" .") or "document"
    return base[:150]


def _pages(db: Session, v: DocumentVersion) -> list[VersionPage]:
    return list(db.scalars(select(VersionPage).where(VersionPage.version_id == v.id, VersionPage.tenant_id == v.tenant_id)
                           .order_by(VersionPage.index)))


def markdown(db: Session, tenant: Tenant, doc: Document, v: DocumentVersion) -> str:
    lines = [f"# {doc.name}", "",
             f"- Customer: {_owner(tenant)}",
             f"- Version: {v.version}{' (in use)' if v.is_active else ''}",
             f"- Original file: {v.original_filename} ({v.file_type.upper()}, {v.size_bytes} bytes)",
             f"- Uploaded: {v.uploaded_at.isoformat() if v.uploaded_at else ''}",
             f"- SHA-256: {v.sha256}",
             f"- Exported from Mentis {__version__}: {utcnow().isoformat(timespec='seconds')}", ""]
    for p in _pages(db, v):
        how = f" (read with OCR, confidence {round(p.ocr_confidence * 100)}%)" if p.method == "ocr" and p.ocr_confidence is not None \
            else " (read with OCR)" if p.method == "ocr" else ""
        lines += [f"## {p.label}{how}", "", (p.text or "").strip() or "_No text read on this page._", ""]
    return "\n".join(lines).rstrip() + "\n"


def as_json(db: Session, tenant: Tenant, doc: Document, v: DocumentVersion) -> dict:
    pages = _pages(db, v)
    labels = {p.index: p.label for p in pages}
    chunks = db.scalars(select(Chunk).where(Chunk.version_id == v.id, Chunk.tenant_id == v.tenant_id).order_by(Chunk.ordinal))
    return {
        "format": JSON_FORMAT,
        "exported_at": utcnow().isoformat(timespec="seconds"), "mentis_version": __version__,
        "customer": _owner(tenant), "general_knowledge_base": tenant.is_global,
        "document": {"name": doc.name, "version": v.version, "in_use": v.is_active, "file_name": v.original_filename,
                     "file_type": v.file_type, "size_bytes": v.size_bytes, "sha256": v.sha256,
                     "uploaded_at": v.uploaded_at.isoformat() if v.uploaded_at else None,
                     "processed_at": v.processed_at.isoformat() if v.processed_at else None, "stats": v.stats or {}},
        "pages": [{"index": p.index, "kind": p.kind, "label": p.label, "method": p.method,
                   "ocr_confidence": p.ocr_confidence, "tables": p.tables, "flags": p.flags or [], "text": p.text or ""}
                  for p in pages],
        "passages": [{"n": c.ordinal, "page": c.page_index, "page_label": labels.get(c.page_index, f"Page {c.page_index}"),
                      "heading": c.heading, "text": c.text} for c in chunks],
    }


def readable(v: DocumentVersion) -> None:
    if v.status != VersionStatus.READY:
        raise ExportError(409, "This version has not been read yet (or reading failed): only the original can be downloaded.")


# --- Everything in use, as a ZIP ----------------------------------------------------------

@dataclass
class Bundle:
    file: tempfile.SpooledTemporaryFile
    count: int
    skipped: int


def _unique(name: str, used: set[str]) -> str:
    base, dot, ext = name.rpartition(".")
    candidate, n = name, 2
    while candidate.lower() in used:
        candidate = f"{base} ({n}).{ext}" if dot else f"{name} ({n})"
        n += 1
    used.add(candidate.lower())
    return candidate


def zip_all(db: Session, tenant: Tenant, fmt: str, read_original, max_bytes: int) -> Bundle:
    """Every document's version in use. `read_original(key) -> bytes` reads the stored file."""
    rows = db.execute(select(Document, DocumentVersion).join(DocumentVersion, DocumentVersion.document_id == Document.id)
                      .where(Document.tenant_id == tenant.id, DocumentVersion.tenant_id == tenant.id,
                             DocumentVersion.is_active.is_(True), DocumentVersion.status == VersionStatus.READY)
                      .order_by(Document.name)).all()
    documents = len(db.scalars(select(Document.id).where(Document.tenant_id == tenant.id)).all())
    if not rows:
        raise ExportError(409, "No document in use to download.")
    if fmt == "original":
        size = sum(v.size_bytes for _, v in rows)
        if size > max_bytes:
            raise ExportError(413, f"The originals take {size // 1_000_000} MB, more than the {max_bytes // 1_000_000} MB "
                                   "of one download. Download them one by one, or ask the administrator to raise MENTIS_EXPORT_MAX_MB.")
    out = tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024)
    used: set[str] = set()
    manifest = []
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for doc, v in rows:
            if fmt == "original":
                name = _unique(stem(doc.name) + "." + v.file_type, used)
                z.writestr(name, read_original(v.storage_key))
            elif fmt == "md":
                name = _unique(stem(doc.name) + ".md", used)
                z.writestr(name, markdown(db, tenant, doc, v))
            else:
                name = _unique(stem(doc.name) + ".json", used)
                z.writestr(name, json.dumps(as_json(db, tenant, doc, v), ensure_ascii=False, indent=1))
            manifest.append({"file": name, "document": doc.name, "version": v.version, "sha256_original": v.sha256})
        z.writestr("manifest.json", json.dumps({
            "format": "mentis-export/1", "customer": _owner(tenant), "exported_at": utcnow().isoformat(timespec="seconds"),
            "mentis_version": __version__, "content": fmt, "files": manifest,
            "not_included": documents - len(manifest),
            "note": "Only documents with a version in use; documents waiting for approval or that could not be read are not included.",
        }, ensure_ascii=False, indent=1))
    out.seek(0)
    return Bundle(out, len(manifest), documents - len(manifest))


def zip_name(tenant: Tenant, fmt: str) -> str:
    label = {"original": "originals", "md": "markdown", "json": "json"}[fmt]
    return f"{stem(_owner(tenant))}-documents-{label}-{utcnow().strftime('%Y%m%d')}.zip"

