"""Remove deleted documentation from saved answers.

An answer keeps the passages it cited (Sources) and its own text, which quotes them. When a
document or a customer is deleted, its content must go from chats too, not only from the index:
the answers that used it lose their text, sources and follow-ups, and say why. The questions stay.
"""

import uuid

from sqlalchemy import or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models import Chat, ChatMessage, Tenant

REMOVED = "This answer was removed: documentation it used was deleted."


def _matches(citation: dict, document_ids: set[str], tenant_id: str | None, names: set[str]) -> bool:
    if not isinstance(citation, dict):
        return False
    if citation.get("document_id") and citation["document_id"] in document_ids:
        return True
    if tenant_id and str(citation.get("tenant_id") or "") == tenant_id:
        # A whole customer deleted; or, for answers saved before citations carried document ids,
        # a citation of that customer's document with the deleted name.
        return not names or (not citation.get("document_id") and citation.get("document") in names)
    return False


def redact(db: Session, *, tenant_id: uuid.UUID, document_ids: list[uuid.UUID] | None = None,
           document_names: list[str] | None = None) -> int:
    """Remove answers that used the given documents of `tenant_id` (all its documents when none are
    given). The caller commits. Returns the number of answers removed."""
    tenant = db.get(Tenant, tenant_id)
    whole = document_ids is None
    doc_ids = {str(d) for d in document_ids or []}
    names = set(document_names or [])
    tid = str(tenant_id)
    # Chats that could have searched this tenant: scoped to it, "All customers" chats, and every
    # chat for the General Knowledge Base (it is searched with each customer).
    chats = select(Chat.id)
    if not (tenant is not None and tenant.is_global):
        chats = chats.where(or_(Chat.scope_tenant_id == tenant_id, Chat.scope_tenant_id.is_(None)))
    removed = 0
    rows = db.scalars(select(ChatMessage).where(ChatMessage.role == "assistant", ChatMessage.chat_id.in_(chats))
                      .execution_options(yield_per=200))
    for m in rows:
        cited = any(_matches(c, doc_ids, tid if (whole or names) else None, set() if whole else names)
                    for c in m.citations or [])
        read = whole and tid in [str(t) for t in (m.searched or [])]
        if not (cited or read):
            continue
        m.content = REMOVED
        m.citations = []
        m.followups = []
        check = dict(m.check or {})
        check.pop("hidden_answer", None)
        check.update(issues=[], redacted=True)
        m.check = check
        for name in ("citations", "followups", "check"):
            flag_modified(m, name)
        removed += 1
    return removed
