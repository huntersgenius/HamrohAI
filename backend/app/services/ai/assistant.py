"""AI companion orchestration (spec 8).

The decision order is fixed and is enforced in code, not by the model:

    emergency?            -> emergency script, no model call
    no assigned doctor?   -> keep answering in the personal thread, but any
                             out-of-scope question points at paid consultation
    in-scope by keywords? -> retrieve; nothing relevant means escalate
    retrieved something?  -> model rewrites the passages, output re-checked
    anything else         -> escalate to *this thread's* doctor

Escalation always goes to the doctor who owns the care thread the patient is
chatting in. It never opens a paid consultation and never reaches a random
doctor.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import RateLimitError
from app.core.i18n import translate
from app.core.logging import get_logger
from app.models.ai import AiEscalation, AiMessage
from app.models.care import CareThread, Diagnosis
from app.models.enums import AiOutcome, DiagnosisStatus, MessageRole, NotificationType
from app.models.profile import DoctorProfile
from app.models.template import DiagnosisTemplate
from app.models.user import User
from app.services.ai import client as llm
from app.services.ai.guardrails import Verdict, check_input, check_output, sanitize_for_prompt
from app.services.ai.retrieval import RetrievedChunk, retrieve

log = get_logger(__name__)


@dataclass(slots=True)
class AssistantReply:
    content: str
    outcome: AiOutcome
    citations: list[dict]
    escalation: AiEscalation | None = None
    doctor_name: str | None = None
    suggest_paid_consultation: bool = False
    tokens_used: int | None = None


async def ask(
    db: AsyncSession,
    *,
    thread: CareThread,
    patient: User,
    message: str,
) -> AssistantReply:
    """Answer one patient message inside ``thread``."""
    await _enforce_daily_limit(db, thread.id)

    locale = patient.locale or "uz"
    question = sanitize_for_prompt(message)

    db.add(AiMessage(care_thread_id=thread.id, role=MessageRole.PATIENT, content=question))
    await db.flush()

    doctor = await _thread_doctor(db, thread)
    check = check_input(question)

    # 1. Emergencies bypass everything, including the model.
    if check.verdict is Verdict.EMERGENCY:
        reply = AssistantReply(
            content=translate("ai.emergency", locale),
            outcome=AiOutcome.EMERGENCY,
            citations=[],
        )
        # A doctor is still told, but the patient is not made to wait for them.
        if doctor is not None:
            reply.escalation = await _escalate(
                db,
                thread=thread,
                patient=patient,
                doctor=doctor,
                question=question,
                reason="emergency",
            )
            reply.doctor_name = _doctor_name(doctor)
        return await _persist_reply(db, thread, reply)

    # 2. Diagnosis/dose requests and injection attempts are never answered.
    if check.verdict is Verdict.ESCALATE:
        return await _persist_reply(
            db,
            thread,
            await _build_escalation_reply(
                db,
                thread=thread,
                patient=patient,
                doctor=doctor,
                question=question,
                reason=check.reason,
                locale=locale,
            ),
        )

    # 3. Retrieval decides whether there is any approved ground to answer from.
    allowed_slugs = await _allowed_protocol_slugs(db, thread)
    hits = await retrieve(
        db,
        question,
        locale=locale,
        allowed_slugs=allowed_slugs,
        top_k=settings.AI_RAG_TOP_K,
        min_score=settings.AI_MIN_RELEVANCE,
    )
    if not hits:
        return await _persist_reply(
            db,
            thread,
            await _build_escalation_reply(
                db,
                thread=thread,
                patient=patient,
                doctor=doctor,
                question=question,
                reason="out_of_protocol",
                locale=locale,
            ),
        )

    # 4. The model only rephrases what retrieval already approved.
    answer_text, tokens = await _compose_answer(question, hits, locale=locale)
    if answer_text is None:
        return await _persist_reply(
            db,
            thread,
            await _build_escalation_reply(
                db,
                thread=thread,
                patient=patient,
                doctor=doctor,
                question=question,
                reason="no_grounded_answer",
                locale=locale,
            ),
        )

    return await _persist_reply(
        db,
        thread,
        AssistantReply(
            content=answer_text,
            outcome=AiOutcome.ANSWERED,
            citations=[
                {
                    "protocol_slug": hit.protocol_slug,
                    "protocol_title": hit.protocol_title,
                    "heading": hit.heading,
                    "chunk_id": hit.chunk_id,
                    "score": hit.score,
                }
                for hit in hits
            ],
            tokens_used=tokens,
        ),
    )


async def _compose_answer(
    question: str, hits: list[RetrievedChunk], *, locale: str
) -> tuple[str | None, int | None]:
    """Turn retrieved passages into the reply shown to the patient."""
    passages = [hit.content for hit in hits]

    if llm.is_enabled():
        try:
            result = await llm.generate(question, passages, locale=locale)
        except llm.LlmUnavailable:
            result = None
        if result is not None and not result.refused and result.text:
            text = result.text.strip()
            if "INSUFFICIENT_PROTOCOL" in text:
                return None, result.tokens_used
            if not check_output(text):
                # The model drifted outside the protocol — discard the answer.
                log.warning("ai.output_rejected")
                return None, result.tokens_used
            return text, result.tokens_used

    # Fallback: the top passage is already approved clinical text, so returning
    # it verbatim is safe and keeps the assistant useful without the model.
    fallback = hits[0].content.strip()
    if len(hits) > 1 and hits[1].score >= hits[0].score * 0.75:
        fallback = f"{fallback}\n\n{hits[1].content.strip()}"
    return fallback, None


async def _build_escalation_reply(
    db: AsyncSession,
    *,
    thread: CareThread,
    patient: User,
    doctor: User | None,
    question: str,
    reason: str,
    locale: str,
) -> AssistantReply:
    """Out-of-scope handling: forward to the thread's doctor, or point at
    paid consultation when the patient has no doctor at all (spec 8)."""
    disclaimer = translate("ai.safety_disclaimer", locale)

    if doctor is None:
        return AssistantReply(
            content=f"{disclaimer}\n\n{translate('ai.no_doctor_notice', locale)}",
            outcome=AiOutcome.NO_DOCTOR,
            citations=[],
            suggest_paid_consultation=True,
        )

    doctor_name = _doctor_name(doctor)
    escalation = await _escalate(
        db, thread=thread, patient=patient, doctor=doctor, question=question, reason=reason
    )
    notice = translate("ai.escalation_notice", locale, doctor_name=doctor_name)
    return AssistantReply(
        content=f"{disclaimer}\n\n{notice}",
        outcome=AiOutcome.ESCALATED,
        citations=[],
        escalation=escalation,
        doctor_name=doctor_name,
    )


async def _escalate(
    db: AsyncSession,
    *,
    thread: CareThread,
    patient: User,
    doctor: User,
    question: str,
    reason: str,
) -> AiEscalation:
    escalation = AiEscalation(
        care_thread_id=thread.id,
        doctor_user_id=doctor.id,
        patient_user_id=patient.id,
        question=question,
        reason=reason,
        ai_note=f"AI could not answer within the approved protocol ({reason}).",
    )
    db.add(escalation)
    await db.flush()

    from app.services.notifications import queue_notification

    await queue_notification(
        db,
        user=doctor,
        type=NotificationType.AI_ESCALATION,
        title_key="push.ai_escalation.title",
        body_key="push.ai_escalation.body",
        params={"patient_name": patient.full_name or "Bemor"},
        data={
            "screen": "escalation",
            "escalation_id": str(escalation.id),
            "care_thread_id": str(thread.id),
        },
    )
    log.info("ai.escalated", thread_id=str(thread.id), reason=reason)
    return escalation


async def _persist_reply(
    db: AsyncSession, thread: CareThread, reply: AssistantReply
) -> AssistantReply:
    db.add(
        AiMessage(
            care_thread_id=thread.id,
            role=MessageRole.ASSISTANT,
            content=reply.content,
            outcome=reply.outcome,
            citations=reply.citations,
            escalation_id=reply.escalation.id if reply.escalation else None,
            tokens_used=reply.tokens_used,
        )
    )
    thread.last_activity_at = datetime.now(UTC)
    await db.flush()
    return reply


async def _thread_doctor(db: AsyncSession, thread: CareThread) -> User | None:
    """The verified doctor who owns this thread, if any.

    Only an approved doctor may receive escalations — an unverified account must
    not be handed clinical questions.
    """
    if thread.doctor_user_id is None:
        return None
    doctor = await db.get(User, thread.doctor_user_id)
    if doctor is None:
        return None
    profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == doctor.id))
    if profile is None or not profile.is_approved:
        return None
    return doctor


async def _allowed_protocol_slugs(db: AsyncSession, thread: CareThread) -> list[str]:
    """Protocols permitted for this thread, from its verified diagnoses.

    Only verified diagnoses drive protocol selection (spec 2.3): unverified,
    patient-entered text must not steer clinical guidance.
    """
    template_ids = list(
        (
            await db.scalars(
                sa.select(Diagnosis.template_id).where(
                    Diagnosis.care_thread_id == thread.id,
                    Diagnosis.status == DiagnosisStatus.VERIFIED,
                    Diagnosis.is_active.is_(True),
                    Diagnosis.template_id.is_not(None),
                )
            )
        ).all()
    )
    if not template_ids:
        return ["general_safety"]

    slugs: set[str] = {"general_safety"}
    templates = (
        await db.scalars(sa.select(DiagnosisTemplate).where(DiagnosisTemplate.id.in_(template_ids)))
    ).all()
    for template in templates:
        slugs.update(str(s) for s in (template.protocol_slugs or []))
    return sorted(slugs)


async def _enforce_daily_limit(db: AsyncSession, thread_id: uuid.UUID) -> None:
    since = datetime.now(UTC) - timedelta(days=1)
    count = await db.scalar(
        sa.select(sa.func.count())
        .select_from(AiMessage)
        .where(
            AiMessage.care_thread_id == thread_id,
            AiMessage.role == MessageRole.PATIENT,
            AiMessage.created_at >= since,
        )
    )
    if (count or 0) >= settings.AI_DAILY_MESSAGE_LIMIT:
        raise RateLimitError("daily assistant limit reached", code="ai_daily_limit")


def _doctor_name(doctor: User) -> str:
    return doctor.full_name or "shifokoringiz"
