"""Care threads and every clinical record that lives inside one.

Spec 2.2 — the care thread is an absolute isolation boundary. A patient may be
connected to several doctors; each connection is its own container and one
doctor's diagnoses, medications, readings, check-ins, documents and AI history
are never visible from another doctor's thread.

Every clinical table below therefore carries ``care_thread_id`` and is *only*
ever queried through :mod:`app.services.access`, which resolves the caller's
right to that specific thread.
"""

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
    CareThreadKind,
    CareThreadStatus,
    ChangeRequestStatus,
    DiagnosisStatus,
    DoseConfirmationChannel,
    DoseStatus,
    InviteStatus,
    ReadingSource,
    enum_column,
)


class CareThread(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "care_threads"

    patient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # NULL for the patient's private "Shaxsiy" container (spec 2.2, last bullet).
    doctor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    kind: Mapped[CareThreadKind] = mapped_column(
        enum_column(CareThreadKind, "care_thread_kind"), nullable=False
    )
    status: Mapped[CareThreadStatus] = mapped_column(
        enum_column(CareThreadStatus, "care_thread_status"),
        default=CareThreadStatus.ACTIVE,
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    connected_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    diagnoses: Mapped[list[Diagnosis]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    medications: Mapped[list[Medication]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )
    metric_series: Mapped[list[MetricSeries]] = relationship(
        back_populates="thread", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # One thread per patient-doctor pair; the personal thread is the row with
        # doctor_user_id NULL, and a partial unique index keeps it singular.
        sa.UniqueConstraint("patient_user_id", "doctor_user_id", name="uq_care_thread_pair"),
        sa.Index(
            "uq_care_thread_personal",
            "patient_user_id",
            unique=True,
            postgresql_where=sa.text("doctor_user_id IS NULL"),
            sqlite_where=sa.text("doctor_user_id IS NULL"),
        ),
        sa.CheckConstraint(
            "(kind = 'personal' AND doctor_user_id IS NULL) "
            "OR (kind = 'doctor' AND doctor_user_id IS NOT NULL)",
            name="ck_care_thread_kind_matches_doctor",
        ),
    )

    @property
    def is_personal(self) -> bool:
        return self.kind == CareThreadKind.PERSONAL


class PatientInvite(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One-time promo code issued by "Mijoz qo'shish" (spec 4.2 tab 1).

    The doctor pre-fills name / phone / diagnosis; redeeming the code creates the
    care thread and copies the pre-filled clinical data into it.
    """

    __tablename__ = "patient_invites"

    doctor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(sa.String(16), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    phone: Mapped[str] = mapped_column(sa.String(20), nullable=False, index=True)
    diagnosis_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("diagnosis_templates.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[InviteStatus] = mapped_column(
        enum_column(InviteStatus, "invite_status"), default=InviteStatus.ISSUED, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    redeemed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    care_thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="SET NULL"), nullable=True
    )
    # Documents attached by the doctor while filling the form.
    document_ids: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)


class Diagnosis(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A diagnosis record, either unverified (patient-entered) or verified (spec 2.3)."""

    __tablename__ = "diagnoses"

    care_thread_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("diagnosis_templates.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[DiagnosisStatus] = mapped_column(
        enum_column(DiagnosisStatus, "diagnosis_status"),
        default=DiagnosisStatus.UNVERIFIED,
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    verified_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    notes: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    thread: Mapped[CareThread] = relationship(back_populates="diagnoses")
    change_requests: Mapped[list[DiagnosisChangeRequest]] = relationship(
        back_populates="diagnosis", cascade="all, delete-orphan"
    )

    @property
    def is_verified(self) -> bool:
        return self.status == DiagnosisStatus.VERIFIED


class DiagnosisChangeRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Patient's "O'zgartirish taklif qilish" on a verified diagnosis (spec 2.3).

    A verified diagnosis is never edited by the patient directly; they may only
    propose a change and the doctor decides.
    """

    __tablename__ = "diagnosis_change_requests"

    diagnosis_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("diagnoses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    proposed_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    comment: Mapped[str] = mapped_column(sa.Text, nullable=False)
    status: Mapped[ChangeRequestStatus] = mapped_column(
        enum_column(ChangeRequestStatus, "change_request_status"),
        default=ChangeRequestStatus.PENDING,
        nullable=False,
        index=True,
    )
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    diagnosis: Mapped[Diagnosis] = relationship(back_populates="change_requests")


class Medication(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A prescribed medicine inside one care thread."""

    __tablename__ = "medications"

    care_thread_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    dose: Mapped[str] = mapped_column(sa.String(80), nullable=False)
    instructions: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    # Local times of day, e.g. ["08:00", "20:00"].
    times: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    # ISO weekdays 1..7; empty means every day.
    weekdays: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    starts_on: Mapped[date] = mapped_column(sa.Date, nullable=False)
    ends_on: Mapped[date | None] = mapped_column(sa.Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False, index=True)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    thread: Mapped[CareThread] = relationship(back_populates="medications")
    doses: Mapped[list[MedicationDose]] = relationship(
        back_populates="medication", cascade="all, delete-orphan"
    )


class MedicationDose(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One scheduled intake. Materialised ahead of time so reminders, IVR calls
    and adherence statistics all read from a single source of truth."""

    __tablename__ = "medication_doses"

    medication_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("medications.id", ondelete="CASCADE"), nullable=False, index=True
    )
    care_thread_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scheduled_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False, index=True)
    status: Mapped[DoseStatus] = mapped_column(
        enum_column(DoseStatus, "dose_status"), default=DoseStatus.PENDING, nullable=False
    )
    taken_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    confirmed_via: Mapped[DoseConfirmationChannel | None] = mapped_column(
        enum_column(DoseConfirmationChannel, "dose_confirmation_channel"), nullable=True
    )
    push_sent_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    call_attempted_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    medication: Mapped[Medication] = relationship(back_populates="doses")

    __table_args__ = (
        sa.UniqueConstraint("medication_id", "scheduled_at", name="uq_dose_medication_slot"),
        sa.Index("ix_dose_status_scheduled", "status", "scheduled_at"),
    )


class MetricSeries(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One tracked indicator inside a thread — e.g. blood glucose.

    Created from the diagnosis template (spec 6) and rendered as one swipeable
    trend chart in both the doctor and patient apps.
    """

    __tablename__ = "metric_series"

    care_thread_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(sa.String(48), nullable=False)
    label: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)  # {uz, ru, en}
    unit: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    value_type: Mapped[str] = mapped_column(sa.String(16), default="number", nullable=False)
    target_min: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    target_max: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    critical_min: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    critical_max: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    decimals: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    chart_type: Mapped[str] = mapped_column(sa.String(16), default="line", nullable=False)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    source_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("diagnosis_templates.id", ondelete="SET NULL"), nullable=True
    )

    thread: Mapped[CareThread] = relationship(back_populates="metric_series")
    readings: Mapped[list[MetricReading]] = relationship(
        back_populates="series", cascade="all, delete-orphan"
    )

    __table_args__ = (sa.UniqueConstraint("care_thread_id", "key", name="uq_series_thread_key"),)


class MetricReading(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "metric_readings"

    series_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("metric_series.id", ondelete="CASCADE"), nullable=False, index=True
    )
    care_thread_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    value: Mapped[float] = mapped_column(sa.Float, nullable=False)
    # Secondary component for paired indicators such as blood pressure (120/80).
    value_secondary: Mapped[float | None] = mapped_column(sa.Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False, index=True)
    source: Mapped[ReadingSource] = mapped_column(
        enum_column(ReadingSource, "reading_source"), default=ReadingSource.PATIENT, nullable=False
    )
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    series: Mapped[MetricSeries] = relationship(back_populates="readings")

    __table_args__ = (sa.Index("ix_reading_series_recorded", "series_id", "recorded_at"),)


class CheckinSubmission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """The patient's answers to the template's scheduled questions (spec 5.2 tab 1)."""

    __tablename__ = "checkin_submissions"

    care_thread_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    local_date: Mapped[date] = mapped_column(sa.Date, nullable=False, index=True)
    slot: Mapped[str] = mapped_column(sa.String(24), default="day", nullable=False)
    # {question_key: answer}
    answers: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(TimestampType, nullable=False)

    __table_args__ = (
        sa.UniqueConstraint("care_thread_id", "local_date", "slot", name="uq_checkin_thread_slot"),
    )


class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An uploaded image / PDF stored in S3-compatible storage inside Uzbekistan."""

    __tablename__ = "documents"

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    care_thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="CASCADE"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    storage_key: Mapped[str] = mapped_column(sa.String(512), unique=True, nullable=False)
    filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    checksum: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)


class ReminderCall(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An outbound IVR call placed when a dose was not confirmed in the app."""

    __tablename__ = "reminder_calls"

    dose_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("medication_doses.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone: Mapped[str] = mapped_column(sa.String(20), nullable=False)
    status: Mapped[str] = mapped_column(sa.String(24), default="scheduled", nullable=False)
    provider_call_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True, index=True)
    placed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    digits: Mapped[str | None] = mapped_column(sa.String(8), nullable=True)
    error: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (sa.UniqueConstraint("dose_id", name="uq_reminder_call_dose"),)
