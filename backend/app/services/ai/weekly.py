"""Weekly per-thread report delivered to the doctor (spec 8).

Contents: indicator trends, medication adherence, and a summary of the week's AI
conversations. The summary is assembled from recorded outcomes rather than
free-form model output, so a doctor is never shown an invented narrative.
"""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import normalize_locale
from app.core.logging import get_logger
from app.models.ai import AiMessage, WeeklyReport
from app.models.care import CareThread, MedicationDose, MetricReading, MetricSeries
from app.models.enums import AiOutcome, DoseStatus, MessageRole, NotificationType
from app.models.user import User

log = get_logger(__name__)

_LABELS = {
    "uz": {
        "adherence": "Dori intizomi",
        "no_data": "Ma'lumot kiritilmagan",
        "readings": "o'lchov",
        "avg": "o'rtacha",
        "out_of_range": "oraliqdan tashqarida",
        "ai_summary": "AI suhbatlari",
        "questions": "savol",
        "escalated": "shifokorga yo'naltirildi",
        "no_activity": "Bu hafta faollik qayd etilmadi.",
    },
    "ru": {
        "adherence": "Приём препаратов",
        "no_data": "Данные не вносились",
        "readings": "измерений",
        "avg": "среднее",
        "out_of_range": "вне диапазона",
        "ai_summary": "Диалоги с ИИ",
        "questions": "вопрос(ов)",
        "escalated": "передано врачу",
        "no_activity": "На этой неделе активности не зафиксировано.",
    },
    "en": {
        "adherence": "Medication adherence",
        "no_data": "No data recorded",
        "readings": "readings",
        "avg": "average",
        "out_of_range": "out of range",
        "ai_summary": "AI conversations",
        "questions": "question(s)",
        "escalated": "escalated to the doctor",
        "no_activity": "No activity recorded this week.",
    },
}


async def build_report(
    db: AsyncSession, thread: CareThread, *, period_end: date | None = None, locale: str = "uz"
) -> tuple[dict, str]:
    """Compute the payload and the human-readable summary for one thread."""
    locale = normalize_locale(locale)
    labels = _LABELS[locale]
    period_end = period_end or datetime.now(UTC).date()
    period_start = period_end - timedelta(days=7)
    start_dt = datetime.combine(period_start, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(period_end, datetime.max.time(), tzinfo=UTC)

    metrics: list[dict] = []
    lines: list[str] = []

    series_list = (
        await db.scalars(
            sa.select(MetricSeries)
            .where(MetricSeries.care_thread_id == thread.id, MetricSeries.is_active.is_(True))
            .order_by(MetricSeries.sort_order)
        )
    ).all()

    for series in series_list:
        readings = list(
            (
                await db.scalars(
                    sa.select(MetricReading)
                    .where(
                        MetricReading.series_id == series.id,
                        MetricReading.recorded_at >= start_dt,
                        MetricReading.recorded_at <= end_dt,
                    )
                    .order_by(MetricReading.recorded_at)
                )
            ).all()
        )
        label = (series.label or {}).get(locale) or (series.label or {}).get("uz") or series.key
        if not readings:
            metrics.append({"key": series.key, "label": label, "count": 0})
            lines.append(f"• {label}: {labels['no_data']}")
            continue

        values = [r.value for r in readings]
        average = round(sum(values) / len(values), series.decimals or 1)
        out_of_range = sum(
            1
            for v in values
            if (series.target_max is not None and v > series.target_max)
            or (series.target_min is not None and v < series.target_min)
        )
        trend = _trend(values)
        metrics.append(
            {
                "key": series.key,
                "label": label,
                "unit": series.unit,
                "count": len(values),
                "average": average,
                "min": min(values),
                "max": max(values),
                "out_of_range": out_of_range,
                "trend": trend,
            }
        )
        line = (
            f"• {label}: {len(values)} {labels['readings']}, "
            f"{labels['avg']} {average} {series.unit}"
        )
        if out_of_range:
            line += f", {out_of_range} {labels['out_of_range']}"
        lines.append(line)

    adherence = await _adherence(db, thread.id, start_dt, end_dt)
    if adherence["due"]:
        lines.append(f"• {labels['adherence']}: {adherence['percent']}%")
    else:
        lines.append(f"• {labels['adherence']}: {labels['no_data']}")

    conversation = await _conversation_summary(db, thread.id, start_dt, end_dt)
    if conversation["questions"]:
        summary_line = (
            f"• {labels['ai_summary']}: {conversation['questions']} {labels['questions']}"
        )
        if conversation["escalated"]:
            summary_line += f", {conversation['escalated']} {labels['escalated']}"
        lines.append(summary_line)
        if conversation["topics"]:
            lines.append("  " + ", ".join(conversation["topics"]))

    flags = _flags(metrics, adherence)
    payload = {
        "metrics": metrics,
        "adherence": adherence,
        "conversation": conversation,
        "flags": flags,
    }
    summary = "\n".join(lines) if lines else labels["no_activity"]
    return payload, summary


def _trend(values: list[float]) -> str:
    """Compare the two halves of the window; 5% is the noise floor."""
    if len(values) < 4:
        return "flat"
    midpoint = len(values) // 2
    first = sum(values[:midpoint]) / midpoint
    second = sum(values[midpoint:]) / (len(values) - midpoint)
    if first == 0:
        return "flat"
    delta = (second - first) / abs(first)
    if delta > 0.05:
        return "up"
    return "down" if delta < -0.05 else "flat"


async def _adherence(
    db: AsyncSession, thread_id: uuid.UUID, start: datetime, end: datetime
) -> dict:
    due = await db.scalar(
        sa.select(sa.func.count())
        .select_from(MedicationDose)
        .where(
            MedicationDose.care_thread_id == thread_id,
            MedicationDose.scheduled_at >= start,
            MedicationDose.scheduled_at <= end,
        )
    )
    if not due:
        return {"due": 0, "taken": 0, "missed": 0, "percent": None}
    taken = await db.scalar(
        sa.select(sa.func.count())
        .select_from(MedicationDose)
        .where(
            MedicationDose.care_thread_id == thread_id,
            MedicationDose.scheduled_at >= start,
            MedicationDose.scheduled_at <= end,
            MedicationDose.status == DoseStatus.TAKEN,
        )
    )
    return {
        "due": due,
        "taken": taken or 0,
        "missed": due - (taken or 0),
        "percent": round((taken or 0) * 100.0 / due, 1),
    }


async def _conversation_summary(
    db: AsyncSession, thread_id: uuid.UUID, start: datetime, end: datetime
) -> dict:
    messages = list(
        (
            await db.scalars(
                sa.select(AiMessage).where(
                    AiMessage.care_thread_id == thread_id,
                    AiMessage.created_at >= start,
                    AiMessage.created_at <= end,
                )
            )
        ).all()
    )
    questions = sum(1 for m in messages if m.role == MessageRole.PATIENT)
    escalated = sum(1 for m in messages if m.outcome == AiOutcome.ESCALATED)
    emergencies = sum(1 for m in messages if m.outcome == AiOutcome.EMERGENCY)

    # Topics come from the protocols actually cited, so the doctor sees what the
    # patient was told rather than a paraphrase of what they asked.
    topics = Counter()
    for message in messages:
        for citation in message.citations or []:
            title = citation.get("protocol_title")
            if title:
                topics[title] += 1

    return {
        "questions": questions,
        "escalated": escalated,
        "emergencies": emergencies,
        "topics": [topic for topic, _ in topics.most_common(3)],
    }


def _flags(metrics: list[dict], adherence: dict) -> list[str]:
    flags = []
    for metric in metrics:
        if metric.get("out_of_range"):
            flags.append(f"{metric['key']}_out_of_range")
    if adherence.get("percent") is not None and adherence["percent"] < 70:
        flags.append("low_adherence")
    return flags


async def generate_and_deliver(
    db: AsyncSession, thread: CareThread, *, period_end: date | None = None
) -> WeeklyReport | None:
    """Build the report for one thread and push it to the doctor."""
    if thread.doctor_user_id is None:
        return None

    doctor = await db.get(User, thread.doctor_user_id)
    patient = await db.get(User, thread.patient_user_id)
    if doctor is None:
        return None

    period_end = period_end or datetime.now(UTC).date()
    period_start = period_end - timedelta(days=7)

    existing = await db.scalar(
        sa.select(WeeklyReport).where(
            WeeklyReport.care_thread_id == thread.id,
            WeeklyReport.period_start == period_start,
        )
    )
    if existing is not None:
        return existing

    payload, summary = await build_report(db, thread, period_end=period_end, locale=doctor.locale)
    report = WeeklyReport(
        care_thread_id=thread.id,
        period_start=period_start,
        period_end=period_end,
        payload=payload,
        summary_text=summary,
        delivered_at=datetime.now(UTC),
    )
    db.add(report)
    await db.flush()

    from app.services.notifications import queue_notification

    await queue_notification(
        db,
        user=doctor,
        type=NotificationType.WEEKLY_REPORT,
        title_key="push.weekly_report.title",
        body_key="push.weekly_report.body",
        params={"patient_name": (patient.full_name if patient else None) or "Bemor"},
        data={
            "screen": "weekly_report",
            "report_id": str(report.id),
            "care_thread_id": str(thread.id),
        },
        dedupe_key=f"weekly:{thread.id}:{period_start.isoformat()}",
    )
    return report
