"""Login with mandatory TOTP, logout, current user, password change."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, current_user
from app.api.schemas import (
    EnrollRequest,
    EnrollResponse,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    UserOut,
    VerifyRequest,
)
from app.core import crypto
from app.core.config import get_settings
from app.core.db import get_db
from app.core.security import (
    hash_password,
    new_totp_secret,
    password_problem,
    read_challenge,
    sign_challenge,
    totp_uri,
    verify_password,
    verify_totp,
)
from app.models import User
from app.models.base import utcnow
from app.services import sessions
from app.services.logs import log_event

router = APIRouter(prefix="/auth", tags=["auth"])

PURPOSE_MFA = "mfa"
PURPOSE_ENROLL = "enroll"
INVALID = "Invalid credentials."
# Hash used to spend the same time on unknown emails as on known ones.
_DUMMY_HASH = hash_password("dummy-Password-123")


def _set_session_cookie(response: Response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        s.session_cookie_name,
        token,
        max_age=s.session_ttl_hours * 3600,
        httponly=True,
        secure=s.cookie_secure,
        samesite="strict",
        path="/",
    )


def _user_from_challenge(db: Session, challenge: str, purposes: set[str]) -> tuple[User, str]:
    payload = read_challenge(get_settings().secret_key, challenge)
    if not payload or payload.get("p") not in purposes:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login step expired. Sign in again.")
    user = db.get(User, uuid.UUID(payload["uid"]))
    if user is None or not user.is_active or sessions.is_locked(user):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID)
    return user, payload["p"]


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    ip = client_ip(request)
    email = body.email.lower()
    user = db.scalar(select(User).where(User.email == email))

    if user is None:
        verify_password(body.password, _DUMMY_HASH)
        log_event(db, "auth.login.failed", level="warning", actor_email=email, ip=ip, detail={"reason": "unknown_user"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID)
    if not user.is_active or sessions.is_locked(user):
        log_event(db, "auth.login.blocked", level="warning", actor=user, ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID)
    if not verify_password(body.password, user.password_hash):
        sessions.register_failed_login(db, user)
        log_event(db, "auth.login.failed", level="warning", actor=user, ip=ip, detail={"reason": "bad_password"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID)

    s = get_settings()
    purpose = PURPOSE_MFA if user.totp_enabled else PURPOSE_ENROLL
    challenge = sign_challenge(s.secret_key, str(user.id), purpose, s.mfa_challenge_ttl_seconds)
    return LoginResponse(
        next_step="mfa_required" if user.totp_enabled else "mfa_enrollment",
        challenge=challenge,
    )


@router.post("/totp/enroll", response_model=EnrollResponse)
def totp_enroll(body: EnrollRequest, db: Session = Depends(get_db)) -> EnrollResponse:
    user, _ = _user_from_challenge(db, body.challenge, {PURPOSE_ENROLL})
    secret = new_totp_secret()
    user.totp_secret_enc = crypto.encrypt(secret)
    db.commit()
    return EnrollResponse(secret=secret, otpauth_uri=totp_uri(secret, user.email, get_settings().totp_issuer))


@router.post("/totp/verify", response_model=UserOut)
def totp_verify(body: VerifyRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> UserOut:
    ip = client_ip(request)
    user, purpose = _user_from_challenge(db, body.challenge, {PURPOSE_MFA, PURPOSE_ENROLL})
    secret = crypto.decrypt(user.totp_secret_enc) if user.totp_secret_enc else None
    if secret is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set up the authenticator first.")
    if not verify_totp(secret, body.code):
        sessions.register_failed_login(db, user)
        log_event(db, "auth.mfa.failed", level="warning", actor=user, ip=ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid code.")

    if purpose == PURPOSE_ENROLL:
        user.totp_enabled = True
        db.commit()
        log_event(db, "auth.mfa.enrolled", actor=user, ip=ip)

    token = sessions.create_session(db, user, ip, request.headers.get("user-agent"))
    _set_session_cookie(response, token)
    log_event(db, "auth.login.success", actor=user, ip=ip)
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    s = get_settings()
    token = request.cookies.get(s.session_cookie_name)
    if token:
        sessions.revoke_session(db, token)
    response.delete_cookie(s.session_cookie_name, path="/")
    log_event(db, "auth.logout", actor=user, ip=client_ip(request))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(current_user)) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is wrong.")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(422, problem)
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = utcnow()
    db.commit()
    # Sign out every other session, keep this browser signed in with a fresh session.
    ip = client_ip(request)
    sessions.revoke_all_sessions(db, user)
    _set_session_cookie(response, sessions.create_session(db, user, ip, request.headers.get("user-agent")))
    log_event(db, "auth.password.changed", actor=user, ip=ip)
