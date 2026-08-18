"""AI companion: protocol corpus, chat messages, escalations, weekly reports.

Spec 8 — the assistant answers strictly from approved protocols (RAG), never
diagnoses, and escalates anything out of scope to the patient's own verified
doctor. Every answer records which protocol chunks backed it, so a clinician can
audit what the patient was told.
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
from app.models.enums import AiOutcome, MessageRole, enum_column


class Protocol(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """An approved clinical protocol document. Curated content only."""

    __tablename__ = "protocols"

    slug: Mapped[str] = mapped_column(sa.String(64), unique=True, nullable=False, index=True)
    title: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    specialty: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    source: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False, index=True)

    chunks: Mapped[list[ProtocolChunk]] = relationship(
        back_populates="protocol", cascade="all, delete-orphan"
    )


class ProtocolChunk(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A retrievable passage. One row per locale so retrieval never mixes languages."""

    __tablename__ = "protocol_chunks"

    protocol_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False, index=True
    )
    locale: Mapped[str] = mapped_column(sa.String(5), nullable=False, index=True)
    heading: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Topic tags used by the lexical retriever alongside the body text.
    tags: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    position: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    protocol: Mapped[Protocol] = relationship(back_populates="chunks")

    __table_args__ = (sa.Index("ix_chunk_protocol_locale", "protocol_id", "locale"),)


class AiMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """One turn of the AI companion chat, scoped to a single care thread.

    Scoping to the thread is what keeps one doctor's context out of another's
    (spec 2.2): the assistant only ever sees the active thread's clinical data.
    """

    __tablename__ = "ai_messages"

    care_thread_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[MessageRole] = mapped_column(
        enum_column(MessageRole, "message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    outcome: Mapped[AiOutcome | None] = mapped_column(
        enum_column(AiOutcome, "ai_outcome"), nullable=True
    )
    # [{protocol_slug, chunk_id, score}] — the evidence behind an assistant turn.
    citations: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)
    escalation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("ai_escalations.id", ondelete="SET NULL"), nullable=True
    )
    tokens_used: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    __table_args__ = (sa.Index("ix_ai_message_thread_created", "care_thread_id", "created_at"),)


class AiEscalation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A question the assistant refused to answer and forwarded to the doctor.

    Never opens a paid consultation — it continues the existing relationship
    with the doctor already assigned to this thread (spec 8).
    """

    __tablename__ = "ai_escalations"

    care_thread_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    doctor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    patient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    question: Mapped[str] = mapped_column(sa.Text, nullable=False)
    ai_note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    reason: Mapped[str] = mapped_column(sa.String(48), nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    answer_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    is_open: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False, index=True)


class WeeklyReport(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Weekly digest generated per active thread and delivered to the doctor.

    Contains indicator trends, medication adherence and a summary of the AI
    conversations (spec 8, last bullets).
    """

    __tablename__ = "weekly_reports"

    care_thread_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[date] = mapped_column(sa.Date, nullable=False)
    period_end: Mapped[date] = mapped_column(sa.Date, nullable=False)
    # {metrics: [...], adherence: {...}, conversation_summary: str, flags: [...]}
    payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    summary_text: Mapped[str] = mapped_column(sa.Text, nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("care_thread_id", "period_start", name="uq_weekly_report_period"),
    )


class ThreadMessage(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Direct doctor <-> patient message inside a care thread.

    Used for escalation replies so the doctor's answer lands back in the same
    thread the patient asked from.
    """

    __tablename__ = "thread_messages"

    care_thread_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sender_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[MessageRole] = mapped_column(
        enum_column(MessageRole, "message_role"), nullable=False
    )
    content: Mapped[str] = mapped_column(sa.Text, nullable=False)
    escalation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("ai_escalations.id", ondelete="SET NULL"), nullable=True
    )
    read_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
