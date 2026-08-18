"""Medication scheduling, dose materialisation and adherence.

Doses are materialised ahead of time rather than computed on the fly, because
three separate subsystems need to agree on the same slot: the patient's "Bugun"
list, the push reminder, and the IVR call that follows an unconfirmed dose.

Times are stored as local wall-clock strings ("08:00") and resolved against
Uzbekistan time, which has a fixed +05:00 offset with no daylight saving — so a
schedule never shifts under the patient.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.care import Medication, MedicationDose
from app.models.enums import DoseConfirmationChannel, DoseStatus

log = get_logger(__name__)

# Uzbekistan is UTC+5 year-round (no DST).
UZ_TZ = timezone(timedelta(hours=5), name="Asia/Tashkent")

# How far ahead doses are materialised.
HORIZON_DAYS = 7
# A dose is only "missed" once this much time has passed without confirmation.
MISSED_AFTER_MINUTES = 180


def local_now() -> datetime:
    return datetime.now(UZ_TZ)


def local_today() -> date:
    return local_now().date()


def to_local(value: datetime) -> datetime:
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).astimezone(UZ_TZ)


def _parse_time(value: str) -> time:
    hour, minute = value.split(":")
    return time(hour=int(hour), minute=int(minute))


def scheduled_slots(medication: Medication, day: date) -> list[datetime]:
    """UTC instants at which ``medication`` is due on ``day``."""
    if not medication.is_active:
        return []
    if day < medication.starts_on:
        return []
    if medication.ends_on and day > medication.ends_on:
        return []
    weekdays = medication.weekdays or []
    if weekdays and day.isoweekday() not in weekdays:
        return []

    slots = []
    for raw in medication.times or []:
        try:
            local_dt = datetime.combine(day, _parse_time(str(raw)), tzinfo=UZ_TZ)
        except (ValueError, AttributeError):
            log.warning("medication.bad_time", medication_id=str(medication.id), value=raw)
            continue
        slots.append(local_dt.astimezone(UTC))
    return slots


async def materialize_doses(
    db: AsyncSession, medication: Medication, *, horizon_days: int = HORIZON_DAYS
) -> int:
    """Create the pending dose rows for the next ``horizon_days``.

    Idempotent: the ``(medication_id, scheduled_at)`` unique constraint means
    re-running only fills gaps. Past doses are never created retroactively.
    """
    today = local_today()
    wanted: set[datetime] = set()
    for offset in range(horizon_days):
        wanted.update(scheduled_slots(medication, today + timedelta(days=offset)))

    now = datetime.now(UTC)
    wanted = {slot for slot in wanted if slot >= now - timedelta(minutes=5)}
    if not wanted:
        return 0

    existing = set(
        (
            await db.scalars(
                sa.select(MedicationDose.scheduled_at).where(
                    MedicationDose.medication_id == medication.id,
                    MedicationDose.scheduled_at >= now - timedelta(minutes=5),
                )
            )
        ).all()
    )
    existing_utc = {(dt if dt.tzinfo else dt.replace(tzinfo=UTC)) for dt in existing}

    created = 0
    for slot in sorted(wanted - existing_utc):
        db.add(
            MedicationDose(
                medication_id=medication.id,
                care_thread_id=medication.care_thread_id,
                scheduled_at=slot,
                status=DoseStatus.PENDING,
            )
        )
        created += 1
    if created:
        await db.flush()
    return created


async def resync_medication(db: AsyncSession, medication: Medication) -> None:
    """Rebuild future doses after a schedule change.

    Only *future, still-pending* doses are dropped: a dose the patient already
    confirmed is history and must survive an edit to the prescription.
    """
    now = datetime.now(UTC)
    await db.execute(
        sa.delete(MedicationDose).where(
            MedicationDose.medication_id == medication.id,
            MedicationDose.scheduled_at > now,
            MedicationDose.status == DoseStatus.PENDING,
        )
    )
    if medication.is_active:
        await materialize_doses(db, medication)
    await db.flush()


async def mark_dose(
    db: AsyncSession,
    dose: MedicationDose,
    *,
    taken: bool,
    channel: DoseConfirmationChannel = DoseConfirmationChannel.APP,
    when: datetime | None = None,
) -> MedicationDose:
    if taken:
        dose.status = DoseStatus.TAKEN
        dose.taken_at = when or datetime.now(UTC)
        dose.confirmed_via = channel
    else:
        dose.status = DoseStatus.SKIPPED
        dose.taken_at = None
        dose.confirmed_via = channel
    await db.flush()
    return dose


async def doses_for_day(
    db: AsyncSession, thread_id: uuid.UUID, day: date | None = None
) -> list[MedicationDose]:
    day = day or local_today()
    start = datetime.combine(day, time.min, tzinfo=UZ_TZ).astimezone(UTC)
    end = start + timedelta(days=1)
    return list(
        (
            await db.scalars(
                sa.select(MedicationDose)
                .where(
                    MedicationDose.care_thread_id == thread_id,
                    MedicationDose.scheduled_at >= start,
                    MedicationDose.scheduled_at < end,
                )
                .order_by(MedicationDose.scheduled_at)
            )
        ).all()
    )


async def adherence_percent(
    db: AsyncSession, thread_id: uuid.UUID, *, days: int = 7, medication_id: uuid.UUID | None = None
) -> float | None:
    """Share of due doses that were confirmed over the trailing window.

    Only doses whose time has passed are counted, so a schedule with an evening
    dose does not read as 50% adherence all morning.
    """
    now = datetime.now(UTC)
    since = now - timedelta(days=days)
    conditions = [
        MedicationDose.care_thread_id == thread_id,
        MedicationDose.scheduled_at >= since,
        MedicationDose.scheduled_at <= now,
    ]
    if medication_id:
        conditions.append(MedicationDose.medication_id == medication_id)

    total = await db.scalar(
        sa.select(sa.func.count()).select_from(MedicationDose).where(*conditions)
    )
    if not total:
        return None
    taken = await db.scalar(
        sa.select(sa.func.count())
        .select_from(MedicationDose)
        .where(*conditions, MedicationDose.status == DoseStatus.TAKEN)
    )
    return round((taken or 0) * 100.0 / total, 1)


async def expire_missed_doses(db: AsyncSession) -> int:
    """Flip long-unconfirmed pending doses to MISSED so adherence stays honest."""
    cutoff = datetime.now(UTC) - timedelta(minutes=MISSED_AFTER_MINUTES)
    result = await db.execute(
        sa.update(MedicationDose)
        .where(
            MedicationDose.status == DoseStatus.PENDING,
            MedicationDose.scheduled_at < cutoff,
        )
        .values(status=DoseStatus.MISSED)
    )
    return result.rowcount or 0
