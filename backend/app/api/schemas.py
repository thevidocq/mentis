"""Request and response models for the API."""

import uuid

from pydantic import BaseModel, EmailStr, Field


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    tenant_id: uuid.UUID | None
    totp_enabled: bool
    preferences: dict = {}
    tenant_name: str | None = None


THEMES = ("light", "medium", "dark")


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=120)
    theme: str | None = None


class SetupStatus(BaseModel):
    needs_setup: bool
    web_setup: bool = False


class SetupRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=120)
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    # "mfa_required": enter the TOTP code; "mfa_enrollment": set up the authenticator first.
    next_step: str
    challenge: str


class EnrollRequest(BaseModel):
    challenge: str


class EnrollResponse(BaseModel):
    secret: str
    otpauth_uri: str


class VerifyRequest(BaseModel):
    challenge: str
    code: str = Field(min_length=6, max_length=8)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
