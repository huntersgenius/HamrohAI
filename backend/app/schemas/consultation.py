"""Consultation contracts (spec 4.2 tab 2, 5.2 tab 3B)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ConsultationStatus, ConsultationTargeting, PaymentProvider
from app.schemas.common import ORMModel


class ConsultationCreateRequest(BaseModel):
    # Exactly one of doctor_user_id / specialty decides the targeting mode.
    doctor_user_id: uuid.UUID | None = None
    specialty: str | None = Field(default=None, max_length=64)
    question: str = Field(min_length=5, max_length=5000)
    # Which care thread to attach as context; None = "Yangi, bog'liq emas".
    care_thread_id: uuid.UUID | None = None
    share_clinical_data: bool = True
    attachment_ids: list[uuid.UUID] = Field(default_factory=list)
    payment_provider: PaymentProvider

    @model_validator(mode="after")
    def _one_target(self) -> ConsultationCreateRequest:
        if bool(self.doctor_user_id) == bool(self.specialty):
            raise ValueError("provide exactly one of doctor_user_id or specialty")
        return self


class ConsultationCreateResponse(BaseModel):
    consultation: ConsultationResponse
    payment_id: uuid.UUID
    # Provider checkout URL the app opens in a webview.
    checkout_url: str
    amount_uzs: int


class ConsultationSnapshotView(BaseModel):
    """Frozen clinical context shown to the answering doctor."""

    diagnoses: list[dict] = Field(default_factory=list)
    medications: list[dict] = Field(default_factory=list)
    recent_readings: list[dict] = Field(default_factory=list)
    patient_age: int | None = None
    patient_gender: str | None = None
    shared: bool = True


class ConsultationResponse(ORMModel):
    id: uuid.UUID
    status: ConsultationStatus
    targeting: ConsultationTargeting
    specialty: str
    question: str
    price_uzs: int
    doctor_user_id: uuid.UUID | None
    doctor_name: str | None = None
    doctor_specialty: str | None = None
    doctor_rating: float | None = None
    patient_user_id: uuid.UUID
    # Hidden for matched requests until claimed — the doctor sees "Anonim".
    patient_name: str | None = None
    answer_text: str | None
    rating: int | None
    review: str | None
    created_at: datetime
    paid_at: datetime | None
    sla_expires_at: datetime | None
    claimed_at: datetime | None
    answered_at: datetime | None
    refunded_at: datetime | None
    snapshot: ConsultationSnapshotView | None = None
    attachments: list = Field(default_factory=list)


class ConsultationListItem(BaseModel):
    """Row in the doctor's incoming queue."""

    id: uuid.UUID
    status: ConsultationStatus
    specialty: str
    # "Anonim — [soha] bo'yicha so'rov" when the request came in via matching.
    display_name: str
    question_preview: str
    price_uzs: int
    created_at: datetime
    sla_expires_at: datetime | None
    rating: int | None = None
    answered_at: datetime | None = None


class ConsultationAnswerRequest(BaseModel):
    answer_text: str = Field(min_length=5, max_length=8000)


class ConsultationRateRequest(BaseModel):
    rating: int = Field(ge=1, le=5)
    review: str | None = Field(default=None, max_length=2000)


class ConsultationPriceQuote(BaseModel):
    specialty: str
    doctor_user_id: uuid.UUID | None = None
    price_uzs: int
    is_doctor_custom: bool = False
    sla_hours: int


class DoctorSearchQuery(BaseModel):
    query: str | None = Field(default=None, max_length=120)
    specialty: str | None = Field(default=None, max_length=64)
    sort: Literal["rating", "price", "experience"] = "rating"
