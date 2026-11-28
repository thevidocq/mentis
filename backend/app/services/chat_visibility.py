"""Which saved answers a user may still read.

Chats are private to their user, but an answer quotes customer documentation (text, sources,
follow-ups). When a customer is no longer assigned to the user, the answers that used it are
hidden: the user's own questions stay, the answer text, its sources and follow-ups do not.
The same rule keeps those answers out of the history sent to the LLM.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chat, ChatMessage, Document, DocumentVersion, Tenant, User
from app.services import access

HIDDEN = ("This answer is hidden: it used documentation that was deleted, or of a customer that is no longer "
          "assigned to you.")


class Visibility:
    def __init__(self, db: Session, user: User | None):
        self.visible = access.tenant_ids(db, user) if user is not None else set()
        rows = list(db.scalars(select(Tenant)))
        self._by_name = {t.name: t.id for t in rows}
        self._general = next((t.id for t in rows if t.is_global), None)
        self._db = db
        self._exists: dict[tuple[str, str], bool] = {}  # ("doc" | "version", id) -> still there

    def _gone(self, message: ChatMessage) -> bool:
        """A document or version the answer cited or read no longer exists (deleted, or purged by
        retention, possibly while the answer was being written): checked on every read, so no race
        with the deletion can keep its text visible."""
        cites = [c for c in message.citations or [] if isinstance(c, dict)]
        docs = {str(c["document_id"]) for c in cites if c.get("document_id")} | {str(d) for d in message.read_documents or []}
        versions = {str(c["version_id"]) for c in cites if c.get("version_id")}
        return not (self._all_exist("doc", docs) and self._all_exist("version", versions))

    def _all_exist(self, kind: str, ids: set[str]) -> bool:
        """Only the ids this answer uses are looked up (once per request each)."""
        todo = {i for i in ids if (kind, i) not in self._exists}
        if todo:
            model = Document if kind == "doc" else DocumentVersion
            parsed = set()
            for i in todo:
                try:
                    parsed.add(uuid.UUID(i))
                except ValueError:
                    self._exists[(kind, i)] = False
            found = {str(x) for x in self._db.scalars(select(model.id).where(model.id.in_(parsed)))} if parsed else set()
            for i in todo:
                self._exists.setdefault((kind, i), i in found)
        return all(self._exists[(kind, i)] for i in ids)

    def _cited_tenant(self, citation: dict) -> uuid.UUID | None:
        tid = citation.get("tenant_id")
        if tid:
            try:
                return uuid.UUID(str(tid))
            except ValueError:
                return None
        # Answers saved before citations carried the tenant id: match by name (unknown = hidden).
        if citation.get("is_general"):
            return self._general
        return self._by_name.get(citation.get("tenant"))

    def hidden(self, chat: Chat, message: ChatMessage) -> bool:
        if message.role != "assistant":
            return False
        if chat.scope_tenant_id is not None and chat.scope_tenant_id not in self.visible:
            return True
        if message.searched is not None:  # every customer whose passages the model read, cited or not
            ids = set()
            for t in message.searched:
                try:
                    ids.add(uuid.UUID(str(t)))
                except ValueError:
                    return True
            if not ids <= self.visible:
                return True
        if (message.check or {}).get("redacted") or self._gone(message):
            return True  # a source of this answer was deleted
        return any(self._cited_tenant(c) not in self.visible for c in message.citations or [] if isinstance(c, dict))
