"""Auth request/response contracts (spec 3)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.phone import normalize_phone
from app.models.enums import AuthProvider, UserRole
from app.schemas.common import ORMModel


class PhoneRequest(BaseModel):
    phone: str = Field(description="Any Uzbek format; normalised to E.164 server-side")

    @field_validator("phone")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_phone(v)


class StartPhoneAuthRequest(PhoneRequest):
    locale: Literal["uz", "ru", "en"] = "uz"


class StartPhoneAuthResponse(BaseModel):
    challenge_id: uuid.UUID
    expires_at: datetime
    resend_available_at: datetime
    # Populated only when OTP_DEBUG_RETURN_CODE is on (never in production).
    debug_code: str | None = None


class VerifyPhoneRequest(BaseModel):
    challenge_id: uuid.UUID
    code: str = Field(min_length=4, max_length=8)


class OAuthGoogleRequest(BaseModel):
    id_token: str
    locale: Literal["uz", "ru", "en"] = "uz"


class OAuthTelegramRequest(BaseModel):
    """Payload produced by the Telegram Login Widget / bot deep-link."""

    id: int
    first_name: str | None = None
    last_name: str | None = None
    username: str | None = None
    photo_url: str | None = None
    auth_date: int
    hash: str
    locale: Literal["uz", "ru", "en"] = "uz"


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: datetime


class AuthState(BaseModel):
    """What the client must do next.

    ``phone_verification_required`` is the gate from spec 3: after Google or
    Telegram sign-in the app must show the phone screen with no skip button.
    """

    phone_verification_required: bool
    role_selection_required: bool
    profile_setup_required: bool
    role: UserRole | None = None


class SessionResponse(BaseModel):
    tokens: TokenPair | None = None
    # Short-lived token that only authorises completing phone verification.
    onboarding_token: str | None = None
    state: AuthState
    user: UserResponse | None = None


class LinkedIdentity(ORMModel):
    provider: AuthProvider
    subject: str
    last_used_at: datetime | None = None


class UserResponse(ORMModel):
    id: uuid.UUID
    phone: str
    phone_verified_at: datetime | None
    role: UserRole | None
    full_name: str | None
    birth_date: date | None
    locale: str
    email: str | None
    avatar_url: str | None
    notify_push_enabled: bool
    notify_preferences: dict
    ivr_reminders_enabled: bool
    created_at: datetime


class SelectRoleRequest(BaseModel):
    role: Literal["patient", "doctor"]


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str | None = None
    device_token: str | None = None


class RegisterDeviceRequest(BaseModel):
    token: str = Field(min_length=8, max_length=512)
    platform: Literal["android", "ios"]
    locale: Literal["uz", "ru", "en"] = "uz"
    app_version: str | None = None


class UpdateMeRequest(BaseModel):
    full_name: str | None = Field(default=None, max_length=160)
    birth_date: date | None = None
    locale: Literal["uz", "ru", "en"] | None = None
    email: str | None = None
    notify_push_enabled: bool | None = None
    notify_preferences: dict | None = None
    ivr_reminders_enabled: bool | None = None
