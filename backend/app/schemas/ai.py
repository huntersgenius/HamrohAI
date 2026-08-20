"""AI companion and notification contracts (spec 8, 9)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import AiOutcome, MessageRole, NotificationType
from app.schemas.common import ORMModel


class AiAskRequest(BaseModel):
    care_thread_id: uuid.UUID | None = None
    message: str = Field(min_length=1, max_length=2000)


class AiCitation(BaseModel):
    protocol_slug: str
    protocol_title: str
    heading: str | None = None
    score: float


class AiMessageResponse(ORMModel):
    id: uuid.UUID
    care_thread_id: uuid.UUID
    role: MessageRole
    content: str
    outcome: AiOutcome | None
    citations: list = Field(default_factory=list)
    created_at: datetime


class AiAskResponse(BaseModel):
    message: AiMessageResponse
    outcome: AiOutcome
    citations: list[AiCitation] = Field(default_factory=list)
    escalated_to_doctor: str | None = None
    # Set when the patient has no assigned doctor and must use paid consultation.
    suggest_paid_consultation: bool = False


class EscalationResponse(ORMModel):
    id: uuid.UUID
    care_thread_id: uuid.UUID
    patient_user_id: uuid.UUID
    patient_name: str | None = None
    question: str
    ai_note: str | None
    reason: str
    is_open: bool
    answer_text: str | None
    created_at: datetime
    answered_at: datetime | None


class EscalationAnswerRequest(BaseModel):
    answer_text: str = Field(min_length=2, max_length=5000)


class ThreadMessageResponse(ORMModel):
    id: uuid.UUID
    care_thread_id: uuid.UUID
    sender_user_id: uuid.UUID
    role: MessageRole
    content: str
    created_at: datetime
    read_at: datetime | None


class WeeklyReportResponse(ORMModel):
    id: uuid.UUID
    care_thread_id: uuid.UUID
    period_start: date
    period_end: date
    summary_text: str
    payload: dict
    created_at: datetime


class NotificationResponse(ORMModel):
    id: uuid.UUID
    type: NotificationType
    title: str
    body: str
    data: dict
    read_at: datetime | None
    created_at: datetime


class NotificationReadRequest(BaseModel):
    ids: list[uuid.UUID] | None = None
    all: bool = False
