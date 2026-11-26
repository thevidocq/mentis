"""Overview of a tenant's documents: what answers can use today, what needs attention, recent changes."""

import uuid
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Chat, ChatMessage, Chunk, Document, DocumentVersion, Tenant, User, VersionPage
from app.models.base import utcnow
from app.services import embeddings

RECENT = 8


def _ver(v: DocumentVersion, name: str) -> dict:
    return {"document_id": str(v.document_id), "document": name, "version": v.version, "status": v.status,
            "approval": v.approval, "is_active": v.is_active, "error": v.error, "uploaded_at": v.uploaded_at}


def build(db: Session, tenant: Tenant) -> dict:
    docs = {d.id: d.name for d in db.scalars(select(Document).where(Document.tenant_id == tenant.id))}
    versions = db.scalars(select(DocumentVersion).where(DocumentVersion.tenant_id == tenant.id)
                          .order_by(DocumentVersion.uploaded_at.desc())).all()
    latest: dict[uuid.UUID, DocumentVersion] = {}
    for v in versions:
        cur = latest.get(v.document_id)
        if cur is None or v.version > cur.version:
            latest[v.document_id] = v
    active = [v for v in versions if v.is_active]
    active_ids = [v.id for v in active]

    attention = []
    for v in sorted(latest.values(), key=lambda x: docs.get(x.document_id, "").lower()):
        if v.status in ("queued", "processing", "failed") or v.approval == "pending":
            attention.append(_ver(v, docs.get(v.document_id, "")))

    by_type: dict[str, int] = {}
    for v in active:
        by_type[v.file_type] = by_type.get(v.file_type, 0) + 1

    pages = sum(int((v.stats or {}).get("pages") or 0) for v in active)
    ocr = sum(int((v.stats or {}).get("ocr_pages") or 0) for v in active)
    passages = db.scalar(select(func.count(Chunk.id)).where(Chunk.version_id.in_(active_ids))) if active_ids else 0
    to_check = {"low_confidence": 0, "empty": 0, "truncated": 0}
    if active_ids:
        for flags in db.scalars(select(VersionPage.flags).where(VersionPage.version_id.in_(active_ids))):
            for f in flags or []:
                if f in to_check:
                    to_check[f] += 1

    last_indexed = max((v for v in active if v.processed_at), key=lambda v: v.processed_at, default=None)
    oldest = min(active, key=lambda v: v.uploaded_at, default=None)

    users = {u.id: u.full_name for u in db.scalars(select(User).where(
        User.id.in_({v.uploaded_by for v in versions[:RECENT] if v.uploaded_by} | {v.reviewed_by for v in versions[:RECENT] if v.reviewed_by})))}
    recent = []
    for v in versions[:RECENT]:
        item = _ver(v, docs.get(v.document_id, ""))
        item["uploaded_by"] = users.get(v.uploaded_by)
        item["reviewed_by"] = users.get(v.reviewed_by)
        recent.append(item)

    questions = None
    if not tenant.is_global:  # the knowledge base is used in every customer's chats: no per-chat count
        since = utcnow() - timedelta(days=30)
        rows = db.execute(select(ChatMessage.status, func.count()).join(Chat, Chat.id == ChatMessage.chat_id)
                          .where(Chat.scope_tenant_id == tenant.id, ChatMessage.role == "assistant", ChatMessage.created_at >= since)
                          .group_by(ChatMessage.status)).all()
        counts = {s: n for s, n in rows}
        questions = {"answered": counts.get("ok", 0), "not_found": counts.get("not_found", 0), "errors": counts.get("error", 0)}

    return {
        "documents": len(latest), "in_use": len(active), "needs_attention": len(attention),
        "pages": pages, "ocr_pages": ocr, "passages": passages or 0,
        "embedding_model": embeddings.get_config(db)["model"],
        "by_type": by_type, "to_check": to_check,
        "last_indexed": _ver(last_indexed, docs.get(last_indexed.document_id, "")) | {"processed_at": last_indexed.processed_at} if last_indexed else None,
        "oldest_in_use": _ver(oldest, docs.get(oldest.document_id, "")) if oldest else None,
        "attention": attention, "recent": recent, "questions": questions,
    }
