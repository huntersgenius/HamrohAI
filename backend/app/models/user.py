"""Identity: users, linked auth providers, OTP challenges, sessions, devices."""

from __future__ import annotations

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    JSONType,
    TimestampMixin,
    TimestampType,
    UUIDPrimaryKeyMixin,
    UUIDType,
)
from app.models.enums import (
    AuthProvider,
    DevicePlatform,
    OtpPurpose,
    UserRole,
    enum_column,
)


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A person. Uniquely identified by verified phone number (spec 2.1).

    Whichever provider the user signs in with, the phone number is the identity
    key: the same number always resolves to this one row, and a new provider is
    attached as an :class:`AuthIdentity` instead of creating a duplicate account.
    """

    __tablename__ = "users"

    phone: Mapped[str] = mapped_column(sa.String(20), unique=True, index=True, nullable=False)
    phone_verified_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    role: Mapped[UserRole | None] = mapped_column(
        enum_column(UserRole, "user_role"), nullable=True, index=True
    )
    full_name: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    birth_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    locale: Mapped[str] = mapped_column(sa.String(5), default="uz", nullable=False)
    email: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(sa.String(512), nullable=True)

    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    is_blocked: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    last_seen_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    # Notification preferences (spec 4.2 tab 4 / 5.2 tab 4).
    notify_push_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    notify_preferences: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    # "Qo'ng'iroq orqali eslatish" — on by default, patient may switch it off.
    ivr_reminders_enabled: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)

    identities: Mapped[list[AuthIdentity]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin"
    )
    devices: Mapped[list[DeviceToken]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    doctor_profile: Mapped[DoctorProfile | None] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )
    patient_profile: Mapped[PatientProfile | None] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (sa.Index("ix_users_role_active", "role", "is_active"),)

    @property
    def is_phone_verified(self) -> bool:
        return self.phone_verified_at is not None

    def wants(self, key: str, default: bool = True) -> bool:
        """Per-category notification opt-in, e.g. ``user.wants("medication_due")``."""
        if not self.notify_push_enabled:
            return False
        prefs = self.notify_preferences or {}
        value = prefs.get(key, default)
        return bool(value)


class AuthIdentity(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A login method attached to a user (google / telegram / phone)."""

    __tablename__ = "auth_identities"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[AuthProvider] = mapped_column(
        enum_column(AuthProvider, "auth_provider"), nullable=False
    )
    # Provider-side stable id: Google "sub", Telegram user id, or the phone itself.
    subject: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    raw_profile: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    user: Mapped[User] = relationship(back_populates="identities")

    __table_args__ = (
        sa.UniqueConstraint("provider", "subject", name="uq_auth_identity_provider_subject"),
        sa.UniqueConstraint("user_id", "provider", name="uq_auth_identity_user_provider"),
    )


class OtpChallenge(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A pending SMS verification. The code itself is never stored in clear."""

    __tablename__ = "otp_challenges"

    phone: Mapped[str] = mapped_column(sa.String(20), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    purpose: Mapped[OtpPurpose] = mapped_column(
        enum_column(OtpPurpose, "otp_purpose"), nullable=False
    )
    attempts: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    # Set when an authenticated user links/changes their phone number.
    requested_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    __table_args__ = (sa.Index("ix_otp_phone_purpose_created", "phone", "purpose", "created_at"),)

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None


class RefreshSession(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A refresh token, stored as a keyed hash and rotated on every use."""

    __tablename__ = "refresh_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(sa.String(128), unique=True, nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    # Set when this session was rotated, so token reuse can be detected.
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)
    user_agent: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None


class DeviceToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Push token for one installation."""

    __tablename__ = "device_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(sa.String(512), unique=True, nullable=False)
    platform: Mapped[DevicePlatform] = mapped_column(
        enum_column(DevicePlatform, "device_platform"), nullable=False
    )
    locale: Mapped[str] = mapped_column(sa.String(5), default="uz", nullable=False)
    app_version: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    user: Mapped[User] = relationship(back_populates="devices")
