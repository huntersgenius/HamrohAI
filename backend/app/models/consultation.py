"""One-off paid consultations (spec 5.2 tab 3B, 4.2 tab 2, 7).

Completely separate from the AI companion flow: a consultation is a single
question, paid up front, answered by one doctor within 24 hours or refunded.
"""

from __future__ import annotations

import uuid
from datetime import datetime

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
from app.models.enums import ConsultationStatus, ConsultationTargeting, enum_column


class Consultation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "consultations"

    patient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Set from the start for DIRECT targeting; set on claim for MATCHED targeting.
    doctor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    targeting: Mapped[ConsultationTargeting] = mapped_column(
        enum_column(ConsultationTargeting, "consultation_targeting"), nullable=False
    )
    specialty: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    question: Mapped[str] = mapped_column(sa.Text, nullable=False)

    # Which care thread this question relates to, if any (spec 5.2 tab 3B).
    # NULL means the patient chose "Yangi, bog'liq emas" and no clinical data is shared.
    care_thread_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("care_threads.id", ondelete="SET NULL"), nullable=True
    )
    # Immutable copy of the clinical context the patient consented to share. Taken
    # at submit time so a later thread edit cannot retroactively change what the
    # doctor was shown.
    snapshot: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    status: Mapped[ConsultationStatus] = mapped_column(
        enum_column(ConsultationStatus, "consultation_status"),
        default=ConsultationStatus.DRAFT,
        nullable=False,
        index=True,
    )
    price_uzs: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    platform_fee_uzs: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    doctor_earning_uzs: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    paid_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    # Deadline for an answer; refund job picks up anything past it (spec 7).
    sla_expires_at: Mapped[datetime | None] = mapped_column(
        TimestampType, nullable=True, index=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    answer_text: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    rating: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)
    review: Mapped[str | None] = mapped_column(sa.Text, nullable=True)
    rated_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)

    attachments: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    payments: Mapped[list[Payment]] = relationship(  # noqa: F821
        back_populates="consultation"
    )

    __table_args__ = (
        sa.CheckConstraint("price_uzs >= 0", name="ck_consultation_price_nonneg"),
        sa.CheckConstraint(
            "rating IS NULL OR (rating >= 1 AND rating <= 5)", name="ck_consultation_rating_range"
        ),
        sa.Index("ix_consultation_open_specialty", "status", "specialty"),
    )

    @property
    def is_open_for_claim(self) -> bool:
        return self.status == ConsultationStatus.OPEN

    @property
    def is_answered(self) -> bool:
        return self.status in (ConsultationStatus.ANSWERED, ConsultationStatus.RATED)
