"""Customer documentation: documents, their versions, extracted pages and chunks.

Every row carries tenant_id so isolation can be enforced with a single filter.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedMixin, IdMixin, utcnow


class Document(IdMixin, CreatedMixin, Base):
    __tablename__ = "documents"
    __table_args__ = (UniqueConstraint("tenant_id", "name_key", name="uq_documents_tenant_name"),)

    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    # Display name, e.g. "Procedure_SOC.pdf". Uploading the same name again creates a new version.
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # Case-insensitive key used to match versions.
    name_key: Mapped[str] = mapped_column(String(255), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)


class VersionStatus:
    QUEUED = "queued"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Approval:
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class DocumentVersion(IdMixin, Base):
    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uq_versions_document_version"),)

    document_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)

    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(10), nullable=False)  # pdf | docx | pptx | xlsx | md | json | csv | tsv | yaml | png | jpg
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[str] = mapped_column(String(12), default=VersionStatus.QUEUED, nullable=False)
    approval: Mapped[str] = mapped_column(String(14), default=Approval.NOT_REQUIRED, nullable=False)
    # Exactly one active version per document is used in answers.
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    note: Mapped[str | None] = mapped_column(String(500))
    error: Mapped[str | None] = mapped_column(Text)
    # Summary of extraction quality: pages, ocr_pages, tables, empty_pages, low_confidence_pages, chars.
    stats: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When the status last became queued or processing: finds versions stuck after a worker crash.
    status_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=utcnow)
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VersionPage(IdMixin, Base):
    """One page (PDF/DOCX), slide (PPTX) or sheet (XLSX) as extracted, for the preview."""

    __tablename__ = "version_pages"

    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    index: Mapped[int] = mapped_column(Integer, nullable=False)        # 1-based
    kind: Mapped[str] = mapped_column(String(8), nullable=False)        # page | slide | sheet
    label: Mapped[str] = mapped_column(String(120), nullable=False)     # "Page 3", "Slide 2", "Sheet Contacts"
    text: Mapped[str] = mapped_column(Text, default="", nullable=False)  # Markdown
    method: Mapped[str] = mapped_column(String(8), nullable=False)      # native | ocr
    ocr_confidence: Mapped[float | None] = mapped_column(Float)          # 0..1 when OCR was used
    tables: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    image_key: Mapped[str | None] = mapped_column(String(255))           # PDF page render in object storage
    flags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)  # e.g. ["empty", "low_confidence"]


class Chunk(IdMixin, Base):
    """Retrieval unit. Embeddings and the Qdrant index are added in the next block."""

    __tablename__ = "chunks"

    version_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("document_versions.id", ondelete="CASCADE"), nullable=False, index=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    page_index: Mapped[int] = mapped_column(Integer, nullable=False)
    heading: Mapped[str | None] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    chars: Mapped[int] = mapped_column(Integer, nullable=False)
