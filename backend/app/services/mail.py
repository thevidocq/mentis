"""SMTP settings (stored in platform_settings, password encrypted) and sending."""

import smtplib
import ssl
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.core import crypto
from app.models import PlatformSetting

SMTP_KEY = "smtp"
SECURITY_MODES = {"starttls", "ssl", "none"}


def get_smtp(db: Session) -> dict:
    row = db.get(PlatformSetting, SMTP_KEY)
    return dict(row.value) if row else {}


def public_smtp(cfg: dict) -> dict:
    """SMTP settings as shown in the panel: the password is never returned."""
    return {
        "host": cfg.get("host", ""),
        "port": cfg.get("port", 587),
        "security": cfg.get("security", "starttls"),
        "username": cfg.get("username", ""),
        "from_address": cfg.get("from_address", ""),
        "password_set": bool(cfg.get("password_enc")),
        "configured": is_configured(cfg),
    }


def save_smtp(db: Session, data: dict) -> dict:
    cfg = get_smtp(db)
    for key in ("host", "port", "security", "username", "from_address"):
        if data.get(key) is not None:
            cfg[key] = data[key]
    if data.get("password") is not None:
        # Empty string clears the password.
        cfg["password_enc"] = crypto.encrypt(data["password"]) if data["password"] else None
    row = db.get(PlatformSetting, SMTP_KEY)
    if row is None:
        db.add(PlatformSetting(key=SMTP_KEY, value=cfg))
    else:
        row.value = cfg
    db.commit()
    return cfg


def is_configured(cfg: dict) -> bool:
    return bool(cfg.get("host") and cfg.get("from_address"))


def send_mail(cfg: dict, to: str, subject: str, body: str) -> None:
    """Send a plain-text email. Raises on failure."""
    msg = EmailMessage()
    msg["From"] = cfg["from_address"]
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    host, port = cfg["host"], int(cfg.get("port", 587))
    security = cfg.get("security", "starttls")
    password = crypto.decrypt(cfg["password_enc"]) if cfg.get("password_enc") else None
    context = ssl.create_default_context()

    if security == "ssl":
        server = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=15)
    with server:
        if security == "starttls":
            server.starttls(context=context)
        if cfg.get("username") and password:
            server.login(cfg["username"], password)
        server.send_message(msg)
