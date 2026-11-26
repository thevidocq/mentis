"""Login with mandatory TOTP, logout, current user, password change."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import client_ip, current_user
from app.api.schemas import (
    THEMES,
    EnrollRequest,
    EnrollResponse,
    LoginRequest,
    LoginResponse,
    PasswordChangeRequest,
    ProfileUpdate,
    TenantRef,
    UserOut,
    VerifyRequest,
)
from app.core import crypto
from app.core.config import get_settings
from app.core.db import get_db
from app.core.ratelimit import auth_rate_limit
from app.core.security import (
    hash_password,
    new_totp_secret,
    password_problem,
    read_challenge,
    sign_challenge,
    totp_step,
    totp_uri,
    verify_password,
)
from app.models import User
from app.models.base import utcnow
from app.services import access, sessions
from app.services.logs import log_event

router = APIRouter(prefix="/auth", tags=["auth"])


def user_out(db: Session, user: User) -> UserOut:
    # The tenants the user can see now (all of them with all_tenants), General first.
    return UserOut(id=user.id, email=user.email, full_name=user.full_name, role=user.role,
                   tenants=[TenantRef(id=t.id, name=t.name, is_general=t.is_global) for t in access.tenants(db, user)],
                   all_tenants=user.all_tenants, can_manage_general=access.manages_general(user),
                   totp_enabled=user.totp_enabled, preferences=user.preferences or {})

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


@router.post("/login", response_model=LoginResponse, dependencies=[Depends(auth_rate_limit)])
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    ip = client_ip(request)
    email = body.email.lower()
    user = db.scalar(select(User).where(User.email == email))

    if user is None:
        verify_password(body.password, _DUMMY_HASH)
        log_event(db, "auth.login.failed", level="warning", actor_email=email, ip=ip, detail={"reason": "unknown_user"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, INVALID)
    if not user.is_active or sessions.is_locked(user):
        # Same work as a real check, so the response time does not reveal disabled or locked accounts.
        verify_password(body.password, _DUMMY_HASH)
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


@router.post("/totp/enroll", response_model=EnrollResponse, dependencies=[Depends(auth_rate_limit)])
def totp_enroll(body: EnrollRequest, db: Session = Depends(get_db)) -> EnrollResponse:
    user, _ = _user_from_challenge(db, body.challenge, {PURPOSE_ENROLL})
    if user.totp_enabled:
        # An enrollment challenge still valid after enrolling must not replace the authenticator.
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login step expired. Sign in again.")
    secret = new_totp_secret()
    user.totp_secret_enc = crypto.encrypt(secret)
    db.commit()
    return EnrollResponse(secret=secret, otpauth_uri=totp_uri(secret, user.email, get_settings().totp_issuer))


@router.post("/totp/verify", response_model=UserOut, dependencies=[Depends(auth_rate_limit)])
def totp_verify(body: VerifyRequest, request: Request, response: Response, db: Session = Depends(get_db)) -> UserOut:
    ip = client_ip(request)
    user, purpose = _user_from_challenge(db, body.challenge, {PURPOSE_MFA, PURPOSE_ENROLL})
    if purpose == PURPOSE_ENROLL and user.totp_enabled:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Login step expired. Sign in again.")
    secret = crypto.decrypt(user.totp_secret_enc) if user.totp_secret_enc else None
    if secret is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Set up the authenticator first.")
    step = totp_step(secret, body.code)
    replayed = step is not None and not sessions.claim_totp_step(db, user, step)
    if step is None or replayed:
        sessions.register_failed_login(db, user)
        log_event(db, "auth.mfa.failed", level="warning", actor=user, ip=ip, detail={"reason": "replayed" if replayed else "wrong_code"})
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "This code was already used. Wait for the next one." if replayed else "Invalid code.")

    if purpose == PURPOSE_ENROLL:
        user.totp_enabled = True
        db.commit()
        log_event(db, "auth.mfa.enrolled", actor=user, ip=ip)

    token = sessions.create_session(db, user, ip, request.headers.get("user-agent"))
    _set_session_cookie(response, token)
    log_event(db, "auth.login.success", actor=user, ip=ip)
    return user_out(db, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db), user: User = Depends(current_user)) -> None:
    s = get_settings()
    token = request.cookies.get(s.session_cookie_name)
    if token:
        sessions.revoke_session(db, token)
    response.delete_cookie(s.session_cookie_name, path="/")
    log_event(db, "auth.logout", actor=user, ip=client_ip(request))


@router.get("/me", response_model=UserOut)
def me(db: Session = Depends(get_db), user: User = Depends(current_user)) -> UserOut:
    return user_out(db, user)


@router.patch("/me", response_model=UserOut)
def update_profile(body: ProfileUpdate, db: Session = Depends(get_db), user: User = Depends(current_user)) -> UserOut:
    if body.full_name is not None:
        if not body.full_name.strip():
            raise HTTPException(422, "The name cannot be empty.")
        user.full_name = body.full_name.strip()
    if body.theme is not None:
        if body.theme not in THEMES:
            raise HTTPException(422, f"Theme must be one of: {', '.join(THEMES)}.")
        user.preferences = {**(user.preferences or {}), "theme": body.theme}
    db.commit()
    return user_out(db, user)


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: PasswordChangeRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> None:
    if not verify_password(body.current_password, user.password_hash):
        # Counts like a failed sign-in: a stolen session cannot guess the password without limit.
        sessions.register_failed_login(db, user)
        log_event(db, "auth.password.change_failed", level="warning", actor=user, ip=client_ip(request))
        if sessions.is_locked(user):
            sessions.revoke_all_sessions(db, user)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Too many wrong passwords. Sign in again later.")
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
