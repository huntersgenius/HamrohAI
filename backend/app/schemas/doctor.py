"""Doctor registration, profile and settings contracts (spec 4)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import DoctorVerificationStatus, SubscriptionStatus
from app.schemas.common import ORMModel


class DoctorRegisterRequest(BaseModel):
    """The "ish qidirish platformasi uslubidagi" registration form (spec 4.1)."""

    full_name: str = Field(min_length=2, max_length=160)
    age: int | None = Field(default=None, ge=18, le=100)
    specialty: str = Field(min_length=2, max_length=64)
    experience_years: int = Field(ge=0, le=70)
    license_document_id: uuid.UUID
    bio: str | None = Field(default=None, max_length=2000)
    workplace: str | None = Field(default=None, max_length=255)


class DoctorProfileResponse(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID
    full_name: str
    age: int | None
    specialty: str
    experience_years: int
    bio: str | None
    workplace: str | None
    verification_status: DoctorVerificationStatus
    verification_note: str | None
    connect_code: str
    consultation_open: bool
    consultation_specialties: list
    consultation_price_uzs: int | None
    rating_average: float | None = None
    rating_count: int
    answered_count: int
    patient_count: int = 0
    subscription: DoctorSubscriptionResponse | None = None
    created_at: datetime


class DoctorSubscriptionResponse(ORMModel):
    plan: str
    status: SubscriptionStatus
    current_period_end: datetime
    is_active: bool = True


class DoctorProfileUpdateRequest(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    age: int | None = Field(default=None, ge=18, le=100)
    specialty: str | None = Field(default=None, min_length=2, max_length=64)
    experience_years: int | None = Field(default=None, ge=0, le=70)
    bio: str | None = Field(default=None, max_length=2000)
    workplace: str | None = Field(default=None, max_length=255)


class ConsultationSettingsRequest(BaseModel):
    """Tab 4 — availability, specialties and price."""

    consultation_open: bool | None = None
    consultation_specialties: list[str] | None = None
    consultation_price_uzs: int | None = Field(default=None, ge=0, le=100_000_000)


class SpecialtyOption(BaseModel):
    code: str
    name: dict
    recommended_price_uzs: int


class DoctorSearchItem(BaseModel):
    """Result row when a patient searches a doctor by name (spec 5.2 tab 3B)."""

    user_id: uuid.UUID
    full_name: str
    specialty: str
    experience_years: int
    rating_average: float | None
    rating_count: int
    consultation_price_uzs: int
    avatar_url: str | None = None
    is_connected: bool = False
