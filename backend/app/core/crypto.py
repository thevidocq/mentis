"""Symmetric encryption for secrets stored in the database (TOTP secrets, connector credentials)."""

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


@lru_cache
def _fernet(secret_key: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(("mentis-secrets:" + secret_key).encode()).digest())
    return Fernet(key)


def _keys() -> MultiFernet:
    """The current key first (it encrypts), then the previous ones (they only decrypt)."""
    s = get_settings()
    previous = [k.strip() for k in (s.secret_key_previous or "").split(",") if k.strip()]
    return MultiFernet([_fernet(s.secret_key), *(_fernet(k) for k in previous)])


def encrypt(value: str) -> str:
    return _fernet(get_settings().secret_key).encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    try:
        return _keys().decrypt(value.encode()).decode()
    except InvalidToken:
        # Usually a changed MENTIS_SECRET_KEY: say so, instead of failing silently.
        logging.getLogger("mentis.crypto").warning(
            "a stored secret could not be decrypted: MENTIS_SECRET_KEY changed? Put the old key in MENTIS_SECRET_KEY_PREVIOUS")
        return None
