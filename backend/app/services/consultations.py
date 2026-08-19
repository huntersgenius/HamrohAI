"""One-off paid consultations (spec 5.2 tab 3B, 4.2 tab 2, 7).

Lifecycle::

    DRAFT -> PENDING_PAYMENT -> OPEN -> CLAIMED -> ANSWERED -> RATED
                                  \\-> REFUNDED (no answer within 24h)

Two properties matter most and are enforced here rather than in the API layer:

* **Claim is exclusive.** A conditional UPDATE means only one doctor can win a
  matched request; every other doctor sees it disappear.
* **Shared data is a snapshot.** What the doctor sees is frozen at submit time
  from the thread the patient consented to share — a later edit in that thread
  never retroactively changes what was disclosed, and a thread the patient did
  not pick is never read at all.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.specialties import recommended_price, specialty_name
from app.core.config import settings
from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.i18n import format_money
from app.core.logging import get_logger
from app.models.care import CareThread, Diagnosis, Medication, MetricReading, MetricSeries
from app.models.consultation import Consultation
from app.models.enums import (
    ConsultationStatus,
    ConsultationTargeting,
    DiagnosisStatus,
    NotificationType,
)
from app.models.profile import DoctorProfile, PatientProfile
from app.models.user import User

log = get_logger(__name__)


async def quote_price(
    db: AsyncSession, *, specialty: str | None, doctor_user_id: uuid.UUID | None
) -> tuple[int, str, bool]:
    """Return ``(price_uzs, specialty, is_doctor_custom)``.

    A doctor's own price wins over the system recommendation (spec 7).
    """
    if doctor_user_id is not None:
        profile = await db.scalar(
            sa.select(DoctorProfile).where(DoctorProfile.user_id == doctor_user_id)
        )
        if profile is None:
            raise NotFoundError("doctor not found", code="doctor_not_found")
        if not profile.is_approved:
            raise ValidationError("doctor is not verified", code="doctor_not_verified")
        if not profile.consultation_open:
            raise ValidationError(
                "doctor is not accepting consultations", code="doctor_not_available"
            )
        resolved = specialty or profile.specialty
        if profile.consultation_price_uzs is not None:
            return profile.consultation_price_uzs, resolved, True
        return recommended_price(resolved), resolved, False

    if not specialty:
        raise ValidationError("specialty is required", code="specialty_required")
    return recommended_price(specialty), specialty, False


async def build_snapshot(
    db: AsyncSession, *, thread: CareThread | None, patient: User, share: bool
) -> dict:
    """Freeze the clinical context the patient agreed to share.

    Only the chosen thread is read. If the patient selected "Yangi, bog'liq emas"
    or declined sharing, the snapshot carries no clinical data at all — the
    care-thread isolation rule holds even for paid consultations.
    """
    profile = await db.scalar(sa.select(PatientProfile).where(PatientProfile.user_id == patient.id))
    age = None
    birth = (profile.birth_date if profile else None) or patient.birth_date
    if birth:
        today = datetime.now(UTC).date()
        age = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))

    snapshot: dict = {
        "shared": bool(thread and share),
        "patient_age": age,
        "patient_gender": profile.gender if profile else None,
        "diagnoses": [],
        "medications": [],
        "recent_readings": [],
    }
    if thread is None or not share:
        return snapshot

    diagnoses = (
        await db.scalars(
            sa.select(Diagnosis).where(
                Diagnosis.care_thread_id == thread.id, Diagnosis.is_active.is_(True)
            )
        )
    ).all()
    snapshot["diagnoses"] = [
        {
            "text": d.text,
            "status": d.status.value,
            "verified": d.status == DiagnosisStatus.VERIFIED,
        }
        for d in diagnoses
    ]

    medications = (
        await db.scalars(
            sa.select(Medication).where(
                Medication.care_thread_id == thread.id, Medication.is_active.is_(True)
            )
        )
    ).all()
    snapshot["medications"] = [
        {"name": m.name, "dose": m.dose, "times": list(m.times or [])} for m in medications
    ]

    since = datetime.now(UTC) - timedelta(days=30)
    series_list = (
        await db.scalars(
            sa.select(MetricSeries).where(
                MetricSeries.care_thread_id == thread.id, MetricSeries.is_active.is_(True)
            )
        )
    ).all()
    for series in series_list:
        readings = (
            await db.scalars(
                sa.select(MetricReading)
                .where(MetricReading.series_id == series.id, MetricReading.recorded_at >= since)
                .order_by(MetricReading.recorded_at.desc())
                .limit(10)
            )
        ).all()
        if not readings:
            continue
        snapshot["recent_readings"].append(
            {
                "key": series.key,
                "label": series.label,
                "unit": series.unit,
                "points": [
                    {
                        "at": r.recorded_at.isoformat(),
                        "value": r.value,
                        "value_secondary": r.value_secondary,
                    }
                    for r in reversed(readings)
                ],
            }
        )
    return snapshot


async def create_consultation(
    db: AsyncSession,
    *,
    patient: User,
    doctor_user_id: uuid.UUID | None,
    specialty: str | None,
    question: str,
    thread: CareThread | None,
    share_clinical_data: bool,
    attachment_ids: list[uuid.UUID],
) -> Consultation:
    price, resolved_specialty, _ = await quote_price(
        db, specialty=specialty, doctor_user_id=doctor_user_id
    )
    snapshot = await build_snapshot(db, thread=thread, patient=patient, share=share_clinical_data)
    consultation = Consultation(
        patient_user_id=patient.id,
        doctor_user_id=doctor_user_id,
        targeting=(
            ConsultationTargeting.DIRECT if doctor_user_id else ConsultationTargeting.MATCHED
        ),
        specialty=resolved_specialty,
        question=question.strip(),
        care_thread_id=thread.id if (thread and share_clinical_data) else None,
        snapshot=snapshot,
        status=ConsultationStatus.PENDING_PAYMENT,
        price_uzs=price,
        attachments=[str(a) for a in attachment_ids],
    )
    db.add(consultation)
    await db.flush()
    return consultation


async def activate_paid_consultation(db: AsyncSession, consultation_id: uuid.UUID) -> None:
    """Payment cleared: open the request and notify the right doctors."""
    consultation = await db.get(Consultation, consultation_id)
    if consultation is None:
        log.warning("consultation.activate_missing", id=str(consultation_id))
        return
    if consultation.status not in (
        ConsultationStatus.DRAFT,
        ConsultationStatus.PENDING_PAYMENT,
    ):
        return  # already active or finished; webhook retry

    now = datetime.now(UTC)
    consultation.status = ConsultationStatus.OPEN
    consultation.paid_at = now
    consultation.sla_expires_at = now + timedelta(hours=settings.CONSULTATION_SLA_HOURS)
    await db.flush()
    await _notify_candidates(db, consultation)
    log.info("consultation.opened", id=str(consultation.id))


async def _notify_candidates(db: AsyncSession, consultation: Consultation) -> None:
    from app.services.notifications import queue_notification

    if consultation.doctor_user_id is not None:
        doctors = [await db.get(User, consultation.doctor_user_id)]
    else:
        doctors = list(
            (
                await db.scalars(
                    sa.select(User)
                    .join(DoctorProfile, DoctorProfile.user_id == User.id)
                    .where(
                        DoctorProfile.consultation_open.is_(True),
                        DoctorProfile.verification_status == "approved",
                        sa.or_(
                            DoctorProfile.specialty == consultation.specialty,
                            # JSON containment is dialect-specific; the extra
                            # specialties list is filtered in Python below.
                            DoctorProfile.consultation_specialties.is_not(None),
                        ),
                        User.is_active.is_(True),
                    )
                    .limit(200)
                )
            ).all()
        )
        doctors = await _filter_by_specialty(db, doctors, consultation.specialty)

    for doctor in doctors:
        if doctor is None:
            continue
        await queue_notification(
            db,
            user=doctor,
            type=NotificationType.CONSULTATION_NEW,
            title_key="push.consultation_new.title",
            body_key="push.consultation_new.body",
            params={
                "specialty": specialty_name(consultation.specialty, doctor.locale),
                "price": format_money(consultation.price_uzs, doctor.locale),
            },
            data={"screen": "consultation", "consultation_id": str(consultation.id)},
            dedupe_key=f"consultation:{consultation.id}:{doctor.id}",
        )


async def _filter_by_specialty(db: AsyncSession, doctors: list[User], specialty: str) -> list[User]:
    if not doctors:
        return []
    profiles = {
        profile.user_id: profile
        for profile in (
            await db.scalars(
                sa.select(DoctorProfile).where(
                    DoctorProfile.user_id.in_([d.id for d in doctors if d])
                )
            )
        ).all()
    }
    return [d for d in doctors if d and specialty in profiles[d.id].specialties()]


async def claim(db: AsyncSession, consultation_id: uuid.UUID, doctor: User) -> Consultation:
    """Assign an open consultation to ``doctor``, exclusively.

    The conditional UPDATE is the whole point: two doctors tapping "Qabul
    qilish" at the same moment cannot both win.
    """
    consultation = await db.get(Consultation, consultation_id)
    if consultation is None:
        raise NotFoundError("consultation not found", code="consultation_not_found")

    if consultation.targeting == ConsultationTargeting.DIRECT:
        if consultation.doctor_user_id != doctor.id:
            raise ForbiddenError("this request is addressed to another doctor", code="not_yours")
    else:
        profile = await db.scalar(
            sa.select(DoctorProfile).where(DoctorProfile.user_id == doctor.id)
        )
        if profile is None or not profile.is_approved:
            raise ForbiddenError("doctor is not verified", code="doctor_not_verified")
        if consultation.specialty not in profile.specialties():
            raise ForbiddenError("specialty mismatch", code="specialty_mismatch")

    now = datetime.now(UTC)
    result = await db.execute(
        sa.update(Consultation)
        .where(
            Consultation.id == consultation_id,
            Consultation.status == ConsultationStatus.OPEN,
        )
        .values(status=ConsultationStatus.CLAIMED, doctor_user_id=doctor.id, claimed_at=now)
    )
    if (result.rowcount or 0) == 0:
        raise ConflictError("this request has already been taken", code="already_claimed")

    await db.refresh(consultation)
    log.info("consultation.claimed", id=str(consultation.id), doctor_id=str(doctor.id))
    return consultation


async def answer(
    db: AsyncSession, consultation_id: uuid.UUID, doctor: User, answer_text: str
) -> Consultation:
    consultation = await db.get(Consultation, consultation_id)
    if consultation is None:
        raise NotFoundError("consultation not found", code="consultation_not_found")
    if consultation.doctor_user_id != doctor.id:
        raise ForbiddenError("not your consultation", code="not_yours")
    if consultation.status != ConsultationStatus.CLAIMED:
        raise ConflictError(
            "consultation cannot be answered in its current state", code="invalid_state"
        )

    now = datetime.now(UTC)
    consultation.answer_text = answer_text.strip()
    consultation.answered_at = now
    consultation.status = ConsultationStatus.ANSWERED
    await db.flush()

    from app.services.billing import credit_consultation_earning

    await credit_consultation_earning(db, consultation, doctor)

    profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == doctor.id))
    if profile is not None:
        profile.answered_count += 1

    patient = await db.get(User, consultation.patient_user_id)
    if patient is not None:
        from app.services.notifications import queue_notification

        await queue_notification(
            db,
            user=patient,
            type=NotificationType.CONSULTATION_ANSWERED,
            title_key="push.consultation_answered.title",
            body_key="push.consultation_answered.body",
            params={"doctor_name": profile.full_name if profile else "Shifokor"},
            data={"screen": "consultation", "consultation_id": str(consultation.id)},
            dedupe_key=f"consultation-answer:{consultation.id}",
        )

    await db.flush()
    log.info("consultation.answered", id=str(consultation.id))
    return consultation


async def rate(
    db: AsyncSession, consultation_id: uuid.UUID, patient: User, rating: int, review: str | None
) -> Consultation:
    consultation = await db.get(Consultation, consultation_id)
    if consultation is None:
        raise NotFoundError("consultation not found", code="consultation_not_found")
    if consultation.patient_user_id != patient.id:
        raise ForbiddenError("not your consultation", code="not_yours")
    if consultation.status != ConsultationStatus.ANSWERED:
        raise ConflictError("only an answered consultation can be rated", code="invalid_state")

    consultation.rating = rating
    consultation.review = (review or "").strip() or None
    consultation.rated_at = datetime.now(UTC)
    consultation.status = ConsultationStatus.RATED

    if consultation.doctor_user_id:
        profile = await db.scalar(
            sa.select(DoctorProfile).where(DoctorProfile.user_id == consultation.doctor_user_id)
        )
        if profile is not None:
            profile.rating_sum += rating
            profile.rating_count += 1
    await db.flush()
    return consultation


async def mark_refunded(
    db: AsyncSession, consultation_id: uuid.UUID, *, reason: str = "sla_expired"
) -> Consultation | None:
    """Refund a consultation nobody answered in time (spec 7)."""
    consultation = await db.get(Consultation, consultation_id)
    if consultation is None:
        return None
    if consultation.status in (
        ConsultationStatus.REFUNDED,
        ConsultationStatus.ANSWERED,
        ConsultationStatus.RATED,
    ):
        return consultation

    now = datetime.now(UTC)
    consultation.status = ConsultationStatus.REFUNDED
    consultation.refunded_at = now

    # The payment row must move with it, or reconciliation against the provider
    # shows money received with no matching refund. Idempotent: a refund that
    # originated at the provider has already set this.
    from app.models.billing import Payment
    from app.models.enums import PaymentStatus

    payments = (
        await db.scalars(
            sa.select(Payment).where(
                Payment.consultation_id == consultation.id,
                Payment.status == PaymentStatus.PAID,
            )
        )
    ).all()
    for payment in payments:
        payment.status = PaymentStatus.REFUNDED
        payment.refunded_at = now
        # Flagged for the finance operator: the provider-side reversal is a
        # manual step in the MVP, exactly like payouts (spec 7).
        payment.provider_payload = {
            **(payment.provider_payload or {}),
            "refund_reason": reason,
            "refund_pending_operator": True,
        }
    await db.flush()

    patient = await db.get(User, consultation.patient_user_id)
    if patient is not None:
        from app.services.notifications import queue_notification

        await queue_notification(
            db,
            user=patient,
            type=NotificationType.CONSULTATION_REFUNDED,
            title_key="push.consultation_refunded.title",
            body_key="push.consultation_refunded.body",
            params={"amount": format_money(consultation.price_uzs, patient.locale)},
            data={"screen": "consultation", "consultation_id": str(consultation.id)},
            dedupe_key=f"consultation-refund:{consultation.id}",
        )
    log.info("consultation.refunded", id=str(consultation.id), reason=reason)
    return consultation


async def expire_unanswered(db: AsyncSession) -> int:
    """Refund every consultation past its 24-hour SLA. Run on a schedule."""
    now = datetime.now(UTC)
    ids = list(
        (
            await db.scalars(
                sa.select(Consultation.id).where(
                    Consultation.status.in_([ConsultationStatus.OPEN, ConsultationStatus.CLAIMED]),
                    Consultation.sla_expires_at.is_not(None),
                    Consultation.sla_expires_at < now,
                )
            )
        ).all()
    )
    for consultation_id in ids:
        await mark_refunded(db, consultation_id, reason="sla_expired")
    return len(ids)


def display_name_for_doctor(consultation: Consultation, patient_name: str | None) -> str:
    """What the doctor sees in the queue.

    A matched request stays anonymous until claimed — the doctor is choosing a
    question, not a person (spec 4.2 tab 2).
    """
    if consultation.targeting == ConsultationTargeting.DIRECT:
        return patient_name or "Bemor"
    if consultation.status in (
        ConsultationStatus.CLAIMED,
        ConsultationStatus.ANSWERED,
        ConsultationStatus.RATED,
    ):
        return patient_name or "Bemor"
    return f"Anonim — {specialty_name(consultation.specialty)} bo'yicha so'rov"
