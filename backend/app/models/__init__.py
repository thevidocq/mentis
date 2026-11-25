"""ORM models. Import every model here so Alembic and metadata.create_all see them."""

from app.models.audit import AuditEvent
from app.models.base import Base
from app.models.document import Approval, Chunk, Document, DocumentVersion, VersionPage, VersionStatus
from app.models.invitation import Invitation
from app.models.platform_setting import PlatformSetting
from app.models.session import AuthSession
from app.models.tenant import Tenant
from app.models.user import Role, User

__all__ = [
    "Approval", "AuditEvent", "AuthSession", "Base", "Chunk", "Document", "DocumentVersion", "Invitation",
    "PlatformSetting", "Role", "Tenant", "User", "VersionPage", "VersionStatus",
]
