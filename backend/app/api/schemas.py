"""Request and response models for the API."""

import uuid
from typing import Annotated

from pydantic import BaseModel, EmailStr, Field, StringConstraints

# A person's name: surrounding spaces removed, never empty.
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class TenantRef(BaseModel):
    id: uuid.UUID
    name: str
    is_general: bool = False


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: str
    tenants: list[TenantRef] = []  # tenant admins and analysts: the customers they see
    all_tenants: bool = False      # every customer, including future ones
    totp_enabled: bool
    preferences: dict = {}


THEMES = ("light", "medium", "dark")


class ProfileUpdate(BaseModel):
    full_name: Name | None = None
    theme: str | None = None


class SetupStatus(BaseModel):
    needs_setup: bool
    web_setup: bool = False


class SetupRequest(BaseModel):
    email: EmailStr
    full_name: Name
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=1024)


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
    current_password: str = Field(max_length=1024)
    new_password: str
