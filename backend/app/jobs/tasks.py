"""Scheduled background jobs.

All jobs are idempotent and safe to run more often than their nominal cadence —
the scheduler is at-least-once, so correctness cannot depend on exact timing.

    every minute   dispatch_medication_reminders   push at the scheduled time
    every minute   dispatch_reminder_calls         IVR after ~18 min of silence
    every 10 min   expire_consultations            24h SLA refunds
    every 15 min   mark_missed_doses               adherence bookkeeping
    hourly         extend_dose_horizon             keep 7 days materialised
    daily 07:00    expire_subscriptions
    weekly Mon 08  weekly_reports                  AI digest to each doctor
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_sessionmaker
from app.core.logging import get_logger
from app.models.care import CareThread, Medication, MedicationDose, ReminderCall
from app.models.enums import CareThreadStatus, DoseStatus, NotificationType
from app.models.user import User

log = get_logger(__name__)

# How long after the scheduled time a push is still worth sending.
PUSH_WINDOW_MINUTES = 5


async def dispatch_medication_reminders(db: AsyncSession) -> int:
    """Push "dori vaqti keldi" for doses that just came due."""
    from app.services.notifications import queue_notification

    now = datetime.now(UTC)
    window_start = now - timedelta(minutes=PUSH_WINDOW_MINUTES)

    rows = (
        await db.execute(
            sa.select(MedicationDose, Medication, CareThread)
            .join(Medication, Medication.id == MedicationDose.medication_id)
            .join(CareThread, CareThread.id == MedicationDose.care_thread_id)
            .where(
                MedicationDose.status == DoseStatus.PENDING,
                MedicationDose.push_sent_at.is_(None),
                MedicationDose.scheduled_at <= now,
                MedicationDose.scheduled_at >= window_start,
            )
            .limit(500)
        )
    ).all()

    sent = 0
    for dose, medication, thread in rows:
        patient = await db.get(User, thread.patient_user_id)
        dose.push_sent_at = now
        if patient is None:
            continue
        await queue_notification(
            db,
            user=patient,
            type=NotificationType.MEDICATION_DUE,
            title_key="push.medication_due.title",
            body_key="push.medication_due.body",
            params={"medication": medication.name, "dose": medication.dose},
            data={
                "screen": "today",
                "dose_id": str(dose.id),
                "care_thread_id": str(thread.id),
            },
            dedupe_key=f"dose-push:{dose.id}",
        )
        sent += 1

    await db.flush()
    if sent:
        log.info("jobs.medication_reminders", sent=sent)
    return sent


async def dispatch_reminder_calls(db: AsyncSession) -> int:
    """Place IVR calls for doses still unconfirmed after the grace period.

    Only for patients who left "Qo'ng'iroq orqali eslatish" enabled.
    """
    if not settings.IVR_ENABLED:
        return 0

    from app.services.ivr import place_reminder_call

    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=settings.IVR_DELAY_MINUTES)
    # Don't ring someone about a dose from this morning if the worker was down.
    floor = now - timedelta(hours=2)

    rows = (
        await db.execute(
            sa.select(MedicationDose, Medication, CareThread)
            .join(Medication, Medication.id == MedicationDose.medication_id)
            .join(CareThread, CareThread.id == MedicationDose.care_thread_id)
            .outerjoin(ReminderCall, ReminderCall.dose_id == MedicationDose.id)
            .where(
                MedicationDose.status == DoseStatus.PENDING,
                MedicationDose.scheduled_at <= cutoff,
                MedicationDose.scheduled_at >= floor,
                MedicationDose.call_attempted_at.is_(None),
                ReminderCall.id.is_(None),
            )
            .limit(100)
        )
    ).all()

    placed = 0
    for dose, medication, thread in rows:
        patient = await db.get(User, thread.patient_user_id)
        dose.call_attempted_at = now
        if patient is None or not patient.ivr_reminders_enabled:
            continue

        call = ReminderCall(
            dose_id=dose.id,
            user_id=patient.id,
            phone=patient.phone,
            status="scheduled",
        )
        db.add(call)
        await db.flush()
        await place_reminder_call(call)
        _ = medication  # name is read from the dose when the webhook builds TwiML
        placed += 1

    await db.flush()
    if placed:
        log.info("jobs.reminder_calls", placed=placed)
    return placed


async def mark_missed_doses(db: AsyncSession) -> int:
    from app.services.medications import expire_missed_doses

    count = await expire_missed_doses(db)
    if count:
        log.info("jobs.missed_doses", count=count)
    return count


async def extend_dose_horizon(db: AsyncSession) -> int:
    """Keep the next 7 days of doses materialised for every active medication."""
    from app.services.medications import materialize_doses

    medications = list(
        (
            await db.scalars(
                sa.select(Medication).where(Medication.is_active.is_(True)).limit(5000)
            )
        ).all()
    )
    created = 0
    for medication in medications:
        created += await materialize_doses(db, medication)
    if created:
        log.info("jobs.dose_horizon", created=created)
    return created


async def expire_consultations(db: AsyncSession) -> int:
    """Refund consultations nobody answered within 24 hours (spec 7)."""
    from app.services.consultations import expire_unanswered

    count = await expire_unanswered(db)
    if count:
        log.info("jobs.consultations_refunded", count=count)
    return count


async def expire_doctor_subscriptions(db: AsyncSession) -> int:
    from app.services.billing import expire_subscriptions

    return await expire_subscriptions(db)


async def generate_weekly_reports(db: AsyncSession) -> int:
    """Weekly AI digest for every active doctor thread (spec 8)."""
    from app.services.ai.weekly import generate_and_deliver

    threads = list(
        (
            await db.scalars(
                sa.select(CareThread)
                .where(
                    CareThread.doctor_user_id.is_not(None),
                    CareThread.status == CareThreadStatus.ACTIVE,
                    CareThread.archived_at.is_(None),
                )
                .limit(10000)
            )
        ).all()
    )
    generated = 0
    for thread in threads:
        try:
            report = await generate_and_deliver(db, thread)
        except Exception as exc:  # noqa: BLE001 - one thread must not stop the batch
            log.error("jobs.weekly_failed", thread_id=str(thread.id), error=str(exc))
            continue
        if report is not None:
            generated += 1
    log.info("jobs.weekly_reports", generated=generated)
    return generated


async def cleanup_expired_otp(db: AsyncSession) -> int:
    from app.models.user import OtpChallenge, RefreshSession

    cutoff = datetime.now(UTC) - timedelta(days=2)
    result = await db.execute(sa.delete(OtpChallenge).where(OtpChallenge.created_at < cutoff))
    deleted = result.rowcount or 0
    stale = datetime.now(UTC) - timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS + 30)
    await db.execute(sa.delete(RefreshSession).where(RefreshSession.expires_at < stale))
    return deleted


# --------------------------------------------------------------------- runner
JOBS = {
    "medication_reminders": dispatch_medication_reminders,
    "reminder_calls": dispatch_reminder_calls,
    "missed_doses": mark_missed_doses,
    "dose_horizon": extend_dose_horizon,
    "expire_consultations": expire_consultations,
    "expire_subscriptions": expire_doctor_subscriptions,
    "weekly_reports": generate_weekly_reports,
    "cleanup_otp": cleanup_expired_otp,
}


async def run_job(name: str) -> int:
    """Execute one job in its own transaction."""
    job = JOBS.get(name)
    if job is None:
        raise KeyError(f"unknown job: {name}")
    async with get_sessionmaker()() as session:
        try:
            result = await job(session)
            await session.commit()
            return result
        except Exception:
            await session.rollback()
            raise
