"""Password hashing, session tokens, TOTP and signed MFA challenges."""

import base64
import hashlib
import hmac
import json
import secrets
import time

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12


# --- Passwords ---------------------------------------------------------------

def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def password_problem(password: str) -> str | None:
    """Return a reason the password is too weak, or None if acceptable."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if password.lower() == password or password.upper() == password:
        return "Password must mix upper and lower case letters."
    if not any(c.isdigit() for c in password):
        return "Password must contain at least one digit."
    return None


# --- Session tokens ----------------------------------------------------------

def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Session tokens are stored hashed, so a database leak does not expose live sessions."""
    return hashlib.sha256(token.encode()).hexdigest()


# --- TOTP --------------------------------------------------------------------

def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, account: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=account, issuer_name=issuer)


def totp_step(secret: str, code: str, now: float | None = None) -> int | None:
    """The 30-second time step the code belongs to (current one ±1), or None if the code is wrong.

    The caller stores the step and refuses steps not newer than the last one used, so a code
    seen once (over a shoulder, in a proxy log) cannot be replayed.
    """
    import hmac
    import time

    code = code.strip().replace(" ", "")
    if not (code.isascii() and code.isdigit()):  # compare_digest refuses non-ASCII strings
        return None
    totp = pyotp.TOTP(secret)
    now = time.time() if now is None else now
    current = int(now // totp.interval)
    for step in (current, current - 1, current + 1):
        if hmac.compare_digest(totp.generate_otp(step), code):
            return step
    return None


def verify_totp(secret: str, code: str) -> bool:
    return totp_step(secret, code) is not None


# --- Signed MFA challenges ---------------------------------------------------
# Issued after a correct password, consumed by the TOTP step. Stateless, short-lived.

def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def sign_challenge(secret_key: str, user_id: str, purpose: str, ttl_seconds: int) -> str:
    payload = {"uid": user_id, "p": purpose, "exp": int(time.time()) + ttl_seconds}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(secret_key.encode(), body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def read_challenge(secret_key: str, token: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(secret_key.encode(), body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig.encode(), expected.encode()):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return payload
