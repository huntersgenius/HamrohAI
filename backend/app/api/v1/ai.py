"""AI companion, escalations, thread messages, weekly reports (spec 8)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, Pagination, VerifiedDoctor
from app.core.errors import ForbiddenError, NotFoundError
from app.models.ai import AiEscalation, AiMessage, ThreadMessage, WeeklyReport
from app.models.enums import MessageRole, NotificationType, UserRole
from app.models.profile import DoctorProfile
from app.models.user import User
from app.schemas.ai import (
    AiAskRequest,
    AiAskResponse,
    AiCitation,
    AiMessageResponse,
    EscalationAnswerRequest,
    EscalationResponse,
    NotificationReadRequest,
    NotificationResponse,
    ThreadMessageResponse,
    WeeklyReportResponse,
)
from app.schemas.common import OkResponse, Page
from app.services.access import get_or_create_personal_thread, resolve_thread
from app.services.ai import assistant
from app.services.ai.weekly import build_report

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/ask", response_model=AiAskResponse)
async def ask_assistant(payload: AiAskRequest, db: DbSession, user: CurrentUser) -> AiAskResponse:
    """Send a message to the AI companion.

    The thread decides the context: the assistant only sees the clinical data of
    the thread being chatted in, and any escalation goes to *that* thread's
    doctor. With no thread specified, the patient's personal container is used.
    """
    if user.role != UserRole.PATIENT:
        raise ForbiddenError("patient role required", code="patient_role_required")

    if payload.care_thread_id is not None:
        access = await resolve_thread(db, payload.care_thread_id, user)
        access.require_patient()
        thread = access.thread
    else:
        thread = await get_or_create_personal_thread(db, user)

    reply = await assistant.ask(db, thread=thread, patient=user, message=payload.message)
    await db.commit()

    message = await db.scalar(
        sa.select(AiMessage)
        .where(AiMessage.care_thread_id == thread.id, AiMessage.role == MessageRole.ASSISTANT)
        .order_by(AiMessage.created_at.desc())
        .limit(1)
    )
    return AiAskResponse(
        message=AiMessageResponse.model_validate(message),
        outcome=reply.outcome,
        citations=[AiCitation(**c) for c in reply.citations],
        escalated_to_doctor=reply.doctor_name,
        suggest_paid_consultation=reply.suggest_paid_consultation,
    )


@router.get("/threads/{thread_id}/messages", response_model=list[AiMessageResponse])
async def list_messages(
    thread_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    before: uuid.UUID | None = None,
) -> list[AiMessageResponse]:
    """Chat history for one thread. Both roles may read it."""
    access = await resolve_thread(db, thread_id, user)
    stmt = sa.select(AiMessage).where(AiMessage.care_thread_id == access.thread_id)

    if before is not None:
        anchor = await db.get(AiMessage, before)
        if anchor is not None:
            stmt = stmt.where(AiMessage.created_at < anchor.created_at)

    messages = (await db.scalars(stmt.order_by(AiMessage.created_at.desc()).limit(limit))).all()
    return [AiMessageResponse.model_validate(m) for m in reversed(list(messages))]


# ----------------------------------------------------------------- escalations
@router.get("/escalations", response_model=Page[EscalationResponse])
async def list_escalations(
    db: DbSession, user: VerifiedDoctor, page: Pagination, open_only: bool = True
) -> Page[EscalationResponse]:
    """Questions the AI forwarded to this doctor."""
    conditions = [AiEscalation.doctor_user_id == user.id]
    if open_only:
        conditions.append(AiEscalation.is_open.is_(True))

    total = (
        await db.scalar(sa.select(sa.func.count()).select_from(AiEscalation).where(*conditions))
    ) or 0
    rows = (
        await db.scalars(
            sa.select(AiEscalation)
            .where(*conditions)
            .order_by(AiEscalation.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
    ).all()

    items = []
    for escalation in rows:
        response = EscalationResponse.model_validate(escalation)
        patient = await db.get(User, escalation.patient_user_id)
        response.patient_name = patient.full_name if patient else None
        items.append(response)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("/escalations/{escalation_id}/answer", response_model=EscalationResponse)
async def answer_escalation(
    escalation_id: uuid.UUID,
    payload: EscalationAnswerRequest,
    db: DbSession,
    user: VerifiedDoctor,
) -> EscalationResponse:
    """The doctor's reply, delivered back into the same care thread."""
    from datetime import UTC, datetime

    escalation = await db.get(AiEscalation, escalation_id)
    if escalation is None or escalation.doctor_user_id != user.id:
        raise NotFoundError("escalation not found", code="escalation_not_found")

    escalation.answer_text = payload.answer_text.strip()
    escalation.answered_at = datetime.now(UTC)
    escalation.is_open = False

    db.add(
        ThreadMessage(
            care_thread_id=escalation.care_thread_id,
            sender_user_id=user.id,
            role=MessageRole.DOCTOR,
            content=escalation.answer_text,
            escalation_id=escalation.id,
        )
    )
    # Mirrored into the AI transcript so the patient sees one continuous chat.
    db.add(
        AiMessage(
            care_thread_id=escalation.care_thread_id,
            role=MessageRole.DOCTOR,
            content=escalation.answer_text,
            escalation_id=escalation.id,
        )
    )

    patient = await db.get(User, escalation.patient_user_id)
    if patient is not None:
        from app.services.notifications import queue_notification

        profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
        await queue_notification(
            db,
            user=patient,
            type=NotificationType.DOCTOR_REPLIED,
            title_key="push.doctor_replied.title",
            body_key="push.doctor_replied.body",
            params={"doctor_name": profile.full_name if profile else "Shifokoringiz"},
            data={
                "screen": "ai",
                "care_thread_id": str(escalation.care_thread_id),
                "escalation_id": str(escalation.id),
            },
            dedupe_key=f"escalation-answer:{escalation.id}",
        )

    await db.commit()
    await db.refresh(escalation)
    response = EscalationResponse.model_validate(escalation)
    response.patient_name = patient.full_name if patient else None
    return response


@router.get("/threads/{thread_id}/thread-messages", response_model=list[ThreadMessageResponse])
async def list_thread_messages(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[ThreadMessageResponse]:
    access = await resolve_thread(db, thread_id, user)
    messages = (
        await db.scalars(
            sa.select(ThreadMessage)
            .where(ThreadMessage.care_thread_id == access.thread_id)
            .order_by(ThreadMessage.created_at)
            .limit(200)
        )
    ).all()
    return [ThreadMessageResponse.model_validate(m) for m in messages]


# -------------------------------------------------------------- weekly reports
@router.get("/threads/{thread_id}/weekly-reports", response_model=list[WeeklyReportResponse])
async def list_weekly_reports(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[WeeklyReportResponse]:
    access = await resolve_thread(db, thread_id, user)
    reports = (
        await db.scalars(
            sa.select(WeeklyReport)
            .where(WeeklyReport.care_thread_id == access.thread_id)
            .order_by(WeeklyReport.period_start.desc())
            .limit(26)
        )
    ).all()
    return [WeeklyReportResponse.model_validate(r) for r in reports]


@router.get("/threads/{thread_id}/weekly-preview", response_model=dict)
async def preview_weekly_report(thread_id: uuid.UUID, db: DbSession, user: VerifiedDoctor) -> dict:
    """The current week's digest on demand, without waiting for Monday."""
    access = await resolve_thread(db, thread_id, user)
    access.require_doctor()
    payload, summary = await build_report(db, access.thread, locale=user.locale)
    return {"summary_text": summary, "payload": payload}


# --------------------------------------------------------------- notifications
notifications_router = APIRouter(prefix="/notifications", tags=["notifications"])


@notifications_router.get("", response_model=Page[NotificationResponse])
async def list_notifications(
    db: DbSession, user: CurrentUser, page: Pagination, unread_only: bool = False
) -> Page[NotificationResponse]:
    from app.models.notification import Notification

    conditions = [Notification.user_id == user.id]
    if unread_only:
        conditions.append(Notification.read_at.is_(None))

    total = (
        await db.scalar(sa.select(sa.func.count()).select_from(Notification).where(*conditions))
    ) or 0
    rows = (
        await db.scalars(
            sa.select(Notification)
            .where(*conditions)
            .order_by(Notification.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
    ).all()
    return Page(
        items=[NotificationResponse.model_validate(n) for n in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@notifications_router.get("/unread-count", response_model=dict)
async def get_unread_count(db: DbSession, user: CurrentUser) -> dict:
    from app.services.notifications import unread_count

    return {"count": await unread_count(db, user.id)}


@notifications_router.post("/read", response_model=OkResponse, status_code=status.HTTP_200_OK)
async def mark_notifications_read(
    payload: NotificationReadRequest, db: DbSession, user: CurrentUser
) -> OkResponse:
    from app.services.notifications import mark_read

    await mark_read(db, user.id, payload.ids, all_=payload.all)
    await db.commit()
    return OkResponse()
