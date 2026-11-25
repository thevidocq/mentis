"""Symmetric encryption for secrets stored in the database (TOTP secrets, connector credentials)."""

import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import get_settings


@lru_cache
def _fernet(secret_key: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(("mentis-secrets:" + secret_key).encode()).digest())
    return Fernet(key)


def encrypt(value: str) -> str:
    return _fernet(get_settings().secret_key).encrypt(value.encode()).decode()


def decrypt(value: str) -> str | None:
    try:
        return _fernet(get_settings().secret_key).decrypt(value.encode()).decode()
    except InvalidToken:
        return None
