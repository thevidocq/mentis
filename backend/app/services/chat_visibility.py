"""Which saved answers a user may still read.

Chats are private to their user, but an answer quotes customer documentation (text, sources,
follow-ups). When a customer is no longer assigned to the user, the answers that used it are
hidden: the user's own questions stay, the answer text, its sources and follow-ups do not.
The same rule keeps those answers out of the history sent to the LLM.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Chat, ChatMessage, Tenant, User
from app.services import access

HIDDEN = "This answer is hidden: it used the documentation of a customer that is no longer assigned to you."


class Visibility:
    def __init__(self, db: Session, user: User | None):
        self.visible = access.tenant_ids(db, user) if user is not None else set()
        rows = list(db.scalars(select(Tenant)))
        self._by_name = {t.name: t.id for t in rows}
        self._general = next((t.id for t in rows if t.is_global), None)

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
        return any(self._cited_tenant(c) not in self.visible for c in message.citations or [] if isinstance(c, dict))
