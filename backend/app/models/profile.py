"""Role profiles: doctor and patient."""

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
    DoctorVerificationStatus,
    SubscriptionPlan,
    SubscriptionStatus,
    enum_column,
)
from app.models.user import User


class DoctorProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Doctor registration form (spec 4.1) plus consultation settings (spec 4.2 tab 4)."""

    __tablename__ = "doctor_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    age: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    specialty: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    experience_years: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    bio: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    workplace: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)

    # Verification is performed manually in the MVP, directly in the database.
    verification_status: Mapped[DoctorVerificationStatus] = mapped_column(
        enum_column(DoctorVerificationStatus, "doctor_verification_status"),
        default=DoctorVerificationStatus.PENDING,
        nullable=False,
        index=True,
    )
    verification_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    # Permanent, reusable code patients enter to connect themselves (spec 4.2 tab 4).
    connect_code: Mapped[str] = mapped_column(
        sa.String(16), unique=True, nullable=False, index=True
    )

    # One-off consultations (spec 4.2 tab 2 + tab 4).
    consultation_open: Mapped[bool] = mapped_column(sa.Boolean, default=False, nullable=False)
    consultation_specialties: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    consultation_price_uzs: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    rating_sum: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    rating_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    answered_count: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    user: Mapped[User] = relationship(back_populates="doctor_profile")
    subscription: Mapped[DoctorSubscription | None] = relationship(
        back_populates="doctor", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (
        sa.CheckConstraint("experience_years >= 0", name="ck_doctor_experience_nonneg"),
        sa.CheckConstraint(
            "consultation_price_uzs IS NULL OR consultation_price_uzs >= 0",
            name="ck_doctor_price_nonneg",
        ),
        sa.Index("ix_doctor_open_specialty", "consultation_open", "specialty"),
    )

    @property
    def rating_average(self) -> float | None:
        if not self.rating_count:
            return None
        return round(self.rating_sum / self.rating_count, 2)

    @property
    def is_approved(self) -> bool:
        return self.verification_status == DoctorVerificationStatus.APPROVED

    def specialties(self) -> list[str]:
        """Specialties this doctor accepts consultations in, primary one included."""
        extra = [s for s in (self.consultation_specialties or []) if isinstance(s, str)]
        return list(dict.fromkeys([self.specialty, *extra]))


class DoctorSubscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Recurring subscription gating patient-management features (spec 7)."""

    __tablename__ = "doctor_subscriptions"

    doctor_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        sa.ForeignKey("doctor_profiles.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    plan: Mapped[SubscriptionPlan] = mapped_column(
        enum_column(SubscriptionPlan, "subscription_plan"),
        default=SubscriptionPlan.MONTHLY,
        nullable=False,
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        enum_column(SubscriptionStatus, "subscription_status"),
        default=SubscriptionStatus.TRIAL,
        nullable=False,
        index=True,
    )
    current_period_end: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    cancelled_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    doctor: Mapped[DoctorProfile] = relationship(back_populates="subscription")


class PatientProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "patient_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    birth_date: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    gender: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)
    region: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    # Free-form allergy / chronic-condition notes the patient keeps for themselves.
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="patient_profile")
