from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class PlatformSetting(Base):
    """Key/value platform configuration edited from the admin panel (e.g. "smtp").

    Secret fields inside a value are stored encrypted (app.core.crypto) under keys ending in "_enc".
    """

    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
