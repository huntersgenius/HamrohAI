"""Care thread, diagnosis, medication, metric and check-in contracts."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.phone import normalize_phone
from app.models.enums import (
    CareThreadKind,
    CareThreadStatus,
    ChangeRequestStatus,
    DiagnosisStatus,
    DoseStatus,
    ReadingSource,
)
from app.schemas.common import ORMModel

TIME_PATTERN = r"^([01]\d|2[0-3]):[0-5]\d$"


# --------------------------------------------------------------------- threads
class CareThreadSummary(ORMModel):
    id: uuid.UUID
    kind: CareThreadKind
    status: CareThreadStatus
    title: str | None
    doctor_user_id: uuid.UUID | None
    doctor_name: str | None = None
    doctor_specialty: str | None = None
    doctor_rating: float | None = None
    patient_user_id: uuid.UUID
    patient_name: str | None = None
    primary_diagnosis: str | None = None
    diagnosis_status: DiagnosisStatus | None = None
    last_activity_at: datetime | None
    connected_at: datetime | None
    unread_messages: int = 0
    created_at: datetime


class ConnectByCodeRequest(BaseModel):
    code: str = Field(min_length=4, max_length=16)

    @field_validator("code")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()


class ConnectByCodeResponse(BaseModel):
    thread: CareThreadSummary
    # True when a one-time invite pre-filled the clinical data and the patient
    # only has to confirm it (spec 5.1 "Doktor kodim bor").
    prefilled: bool = False
    prefilled_name: str | None = None
    prefilled_diagnosis: str | None = None


class InvitePreviewResponse(BaseModel):
    """What the patient sees before pressing "Tasdiqlash va davom etish"."""

    doctor_name: str
    doctor_specialty: str
    full_name: str
    phone_masked: str
    diagnosis_text: str | None
    template_name: str | None


class ShareThreadRequest(BaseModel):
    """Consent dialog when a personal thread is merged into a doctor thread."""

    source_thread_id: uuid.UUID
    consent: bool


# ------------------------------------------------------------------ diagnoses
class DiagnosisResponse(ORMModel):
    id: uuid.UUID
    care_thread_id: uuid.UUID
    text: str
    status: DiagnosisStatus
    template_id: uuid.UUID | None
    template_name: str | None = None
    is_active: bool
    notes: str | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime
    pending_change_request: DiagnosisChangeRequestResponse | None = None


class DiagnosisCreateRequest(BaseModel):
    text: str = Field(min_length=2, max_length=4000)
    template_id: uuid.UUID | None = None
    # When omitted the server auto-matches a template from the text (spec 6).
    auto_match_template: bool = True
    notes: str | None = Field(default=None, max_length=4000)


class DiagnosisUpdateRequest(BaseModel):
    text: str | None = Field(default=None, min_length=2, max_length=4000)
    template_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=4000)
    is_active: bool | None = None


class DiagnosisChangeRequestCreate(BaseModel):
    comment: str = Field(min_length=2, max_length=2000)
    proposed_text: str | None = Field(default=None, max_length=4000)


class DiagnosisChangeRequestResponse(ORMModel):
    id: uuid.UUID
    diagnosis_id: uuid.UUID
    comment: str
    proposed_text: str | None
    status: ChangeRequestStatus
    resolution_note: str | None
    created_at: datetime
    resolved_at: datetime | None


class DiagnosisChangeResolve(BaseModel):
    accept: bool
    resolution_note: str | None = Field(default=None, max_length=2000)
    # When accepting, the doctor may adjust the text before it is applied.
    final_text: str | None = Field(default=None, max_length=4000)


class TemplateMatchRequest(BaseModel):
    text: str = Field(min_length=2, max_length=4000)


class TemplateMatchResponse(BaseModel):
    template_id: uuid.UUID | None
    template_name: str | None
    confidence: float
    alternatives: list[TemplateOption] = Field(default_factory=list)


class TemplateOption(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    specialty: str | None = None


class DiagnosisTemplateResponse(ORMModel):
    id: uuid.UUID
    code: str
    name: dict
    description: dict
    specialty: str | None
    metrics: list
    checkin_questions: list
    version: int


# ---------------------------------------------------------------- medications
class MedicationCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    dose: str = Field(min_length=1, max_length=80)
    instructions: str | None = Field(default=None, max_length=2000)
    times: list[str] = Field(min_length=1, max_length=8)
    weekdays: list[int] = Field(default_factory=list)
    starts_on: date | None = None
    ends_on: date | None = None

    @field_validator("times")
    @classmethod
    def _valid_times(cls, v: list[str]) -> list[str]:
        import re

        for t in v:
            if not re.match(TIME_PATTERN, t):
                raise ValueError(f"invalid time '{t}', expected HH:MM")
        return sorted(set(v))

    @field_validator("weekdays")
    @classmethod
    def _valid_weekdays(cls, v: list[int]) -> list[int]:
        if any(d < 1 or d > 7 for d in v):
            raise ValueError("weekdays must be ISO numbers 1..7")
        return sorted(set(v))

    @model_validator(mode="after")
    def _date_order(self) -> MedicationCreateRequest:
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("ends_on must not precede starts_on")
        return self


class MedicationUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    dose: str | None = Field(default=None, min_length=1, max_length=80)
    instructions: str | None = Field(default=None, max_length=2000)
    times: list[str] | None = None
    weekdays: list[int] | None = None
    ends_on: date | None = None
    is_active: bool | None = None


class MedicationResponse(ORMModel):
    id: uuid.UUID
    care_thread_id: uuid.UUID
    name: str
    dose: str
    instructions: str | None
    times: list
    weekdays: list
    starts_on: date
    ends_on: date | None
    is_active: bool
    adherence_7d: float | None = None


class DoseResponse(ORMModel):
    id: uuid.UUID
    medication_id: uuid.UUID
    medication_name: str | None = None
    dose_text: str | None = None
    care_thread_id: uuid.UUID
    scheduled_at: datetime
    status: DoseStatus
    taken_at: datetime | None
    confirmed_via: str | None = None


class MarkDoseRequest(BaseModel):
    taken: bool = True
    taken_at: datetime | None = None


# -------------------------------------------------------------------- metrics
class MetricSeriesResponse(ORMModel):
    id: uuid.UUID
    care_thread_id: uuid.UUID
    key: str
    label: dict
    unit: str
    value_type: str
    target_min: float | None
    target_max: float | None
    critical_min: float | None
    critical_max: float | None
    decimals: int
    chart_type: str
    sort_order: int
    latest_value: float | None = None
    latest_recorded_at: datetime | None = None
    trend: Literal["up", "down", "flat"] | None = None


class MetricSeriesCreateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=48, pattern=r"^[a-z0-9_]+$")
    label: dict[str, str]
    unit: str = Field(max_length=24)
    value_type: Literal["number", "pair"] = "number"
    target_min: float | None = None
    target_max: float | None = None
    critical_min: float | None = None
    critical_max: float | None = None
    decimals: int = Field(default=1, ge=0, le=3)
    chart_type: Literal["line", "bar", "range"] = "line"


class MetricSeriesUpdateRequest(BaseModel):
    label: dict[str, str] | None = None
    unit: str | None = Field(default=None, max_length=24)
    target_min: float | None = None
    target_max: float | None = None
    critical_min: float | None = None
    critical_max: float | None = None
    is_active: bool | None = None


class ReadingCreateRequest(BaseModel):
    value: float
    value_secondary: float | None = None
    recorded_at: datetime | None = None
    note: str | None = Field(default=None, max_length=1000)


class ReadingResponse(ORMModel):
    id: uuid.UUID
    series_id: uuid.UUID
    value: float
    value_secondary: float | None
    recorded_at: datetime
    source: ReadingSource
    note: str | None


class TrendPoint(BaseModel):
    at: datetime
    value: float
    value_secondary: float | None = None


class TrendResponse(BaseModel):
    series: MetricSeriesResponse
    points: list[TrendPoint]
    average: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    in_target_percent: float | None = None


# ------------------------------------------------------------------- check-in
class CheckinQuestionView(BaseModel):
    key: str
    prompt: dict
    type: str
    unit: str | None = None
    metric_key: str | None = None
    options: list[Any] = Field(default_factory=list)
    required: bool = True


class TodayResponse(BaseModel):
    """Everything the patient's "Bugun" tab renders for one thread."""

    care_thread_id: uuid.UUID
    local_date: date
    questions: list[CheckinQuestionView]
    already_submitted: bool
    doses: list[DoseResponse]
    submitted_answers: dict = Field(default_factory=dict)


class CheckinSubmitRequest(BaseModel):
    local_date: date | None = None
    slot: str = "day"
    answers: dict[str, Any]


class CheckinResponse(ORMModel):
    id: uuid.UUID
    care_thread_id: uuid.UUID
    local_date: date
    slot: str
    answers: dict
    submitted_at: datetime


# ------------------------------------------------------------------ documents
class DocumentResponse(ORMModel):
    id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    purpose: str
    care_thread_id: uuid.UUID | None
    created_at: datetime
    download_url: str | None = None


# -------------------------------------------------------------------- invites
class PatientInviteCreateRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    phone: str
    diagnosis_text: str | None = Field(default=None, max_length=4000)
    template_id: uuid.UUID | None = None
    document_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("phone")
    @classmethod
    def _normalize(cls, v: str) -> str:
        return normalize_phone(v)


class PatientInviteResponse(ORMModel):
    id: uuid.UUID
    code: str
    full_name: str
    phone: str
    diagnosis_text: str | None
    template_id: uuid.UUID | None
    template_name: str | None = None
    status: str
    expires_at: datetime
    created_at: datetime
    share_text: str | None = None


class PatientListItem(BaseModel):
    """A card in the doctor's "Bemorlarim" list."""

    care_thread_id: uuid.UUID
    patient_user_id: uuid.UUID | None
    full_name: str
    phone: str | None = None
    primary_diagnosis: str | None = None
    diagnosis_status: DiagnosisStatus | None = None
    last_activity_at: datetime | None = None
    # green / amber / red — derived from adherence and out-of-range readings.
    risk_level: Literal["green", "amber", "red"] = "green"
    risk_reasons: list[str] = Field(default_factory=list)
    pending_invite_code: str | None = None
    is_pending_invite: bool = False
    open_escalations: int = 0
