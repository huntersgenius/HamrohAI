"""Consultation endpoints (spec 4.2 tab 2, 5.2 tab 3B)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Query, status

from app.api.deps import CurrentUser, DbSession, Pagination, VerifiedDoctor
from app.core.config import settings
from app.core.errors import ForbiddenError, NotFoundError
from app.models.care import CareThread
from app.models.consultation import Consultation
from app.models.enums import ConsultationStatus, ConsultationTargeting, PaymentPurpose
from app.models.profile import DoctorProfile
from app.models.user import User
from app.schemas.common import Page
from app.schemas.consultation import (
    ConsultationAnswerRequest,
    ConsultationCreateRequest,
    ConsultationCreateResponse,
    ConsultationListItem,
    ConsultationPriceQuote,
    ConsultationRateRequest,
    ConsultationResponse,
    ConsultationSnapshotView,
)
from app.services import consultations as service
from app.services.access import resolve_thread
from app.services.billing import build_checkout_url, create_payment

router = APIRouter(prefix="/consultations", tags=["consultations"])


@router.get("/quote", response_model=ConsultationPriceQuote)
async def get_quote(
    db: DbSession,
    user: CurrentUser,
    specialty: str | None = Query(default=None),
    doctor_user_id: uuid.UUID | None = Query(default=None),
) -> ConsultationPriceQuote:
    """Price shown before the patient commits (spec 7)."""
    price, resolved, custom = await service.quote_price(
        db, specialty=specialty, doctor_user_id=doctor_user_id
    )
    return ConsultationPriceQuote(
        specialty=resolved,
        doctor_user_id=doctor_user_id,
        price_uzs=price,
        is_doctor_custom=custom,
        sla_hours=settings.CONSULTATION_SLA_HOURS,
    )


@router.post("", response_model=ConsultationCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_consultation(
    payload: ConsultationCreateRequest, db: DbSession, user: CurrentUser
) -> ConsultationCreateResponse:
    """Submit a question and get a checkout URL.

    The consultation stays invisible to doctors until the payment webhook
    confirms it (spec 7): the patient pays in full first.
    """
    thread: CareThread | None = None
    if payload.care_thread_id is not None:
        # Resolving through the access layer proves the patient owns the thread
        # they are attaching, so no one can attach someone else's data.
        access = await resolve_thread(db, payload.care_thread_id, user)
        access.require_patient()
        thread = access.thread

    consultation = await service.create_consultation(
        db,
        patient=user,
        doctor_user_id=payload.doctor_user_id,
        specialty=payload.specialty,
        question=payload.question,
        thread=thread,
        share_clinical_data=payload.share_clinical_data,
        attachment_ids=payload.attachment_ids,
    )
    payment = await create_payment(
        db,
        user=user,
        provider=payload.payment_provider,
        purpose=PaymentPurpose.CONSULTATION,
        amount_uzs=consultation.price_uzs,
        consultation_id=consultation.id,
    )
    await db.commit()
    await db.refresh(consultation)

    return ConsultationCreateResponse(
        consultation=await _response(db, consultation, viewer=user),
        payment_id=payment.id,
        checkout_url=build_checkout_url(payment),
        amount_uzs=payment.amount_uzs,
    )


@router.get("/mine", response_model=Page[ConsultationResponse])
async def list_my_consultations(
    db: DbSession, user: CurrentUser, page: Pagination
) -> Page[ConsultationResponse]:
    """The patient's own requests and their answers."""
    conditions = [
        Consultation.patient_user_id == user.id,
        Consultation.status != ConsultationStatus.PENDING_PAYMENT,
    ]
    total = (
        await db.scalar(sa.select(sa.func.count()).select_from(Consultation).where(*conditions))
    ) or 0
    rows = (
        await db.scalars(
            sa.select(Consultation)
            .where(*conditions)
            .order_by(Consultation.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
    ).all()
    return Page(
        items=[await _response(db, c, viewer=user) for c in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/inbox", response_model=Page[ConsultationListItem])
async def list_inbox(
    db: DbSession, user: VerifiedDoctor, page: Pagination
) -> Page[ConsultationListItem]:
    """Incoming requests for this doctor (spec 4.2 tab 2).

    Shows requests addressed to them directly plus open requests matching a
    specialty they accept. A claimed request disappears from everyone else's list.
    """
    profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
    if profile is None:
        raise NotFoundError("doctor profile not found", code="profile_not_found")

    specialties = profile.specialties()
    condition = sa.or_(
        sa.and_(
            Consultation.doctor_user_id == user.id,
            Consultation.status.in_([ConsultationStatus.OPEN, ConsultationStatus.CLAIMED]),
        ),
        sa.and_(
            Consultation.status == ConsultationStatus.OPEN,
            Consultation.targeting == ConsultationTargeting.MATCHED,
            Consultation.specialty.in_(specialties),
            Consultation.doctor_user_id.is_(None),
        ),
    )
    if not profile.consultation_open:
        # Closed for new work, but requests already assigned still show up.
        condition = sa.and_(
            Consultation.doctor_user_id == user.id,
            Consultation.status.in_([ConsultationStatus.OPEN, ConsultationStatus.CLAIMED]),
        )

    total = (
        await db.scalar(sa.select(sa.func.count()).select_from(Consultation).where(condition))
    ) or 0
    rows = (
        await db.scalars(
            sa.select(Consultation)
            .where(condition)
            .order_by(Consultation.created_at.asc())
            .limit(page.limit)
            .offset(page.offset)
        )
    ).all()
    return Page(
        items=[await _list_item(db, c) for c in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/history", response_model=Page[ConsultationListItem])
async def list_history(
    db: DbSession, user: VerifiedDoctor, page: Pagination
) -> Page[ConsultationListItem]:
    """Answered consultations with the rating the patient gave."""
    conditions = [
        Consultation.doctor_user_id == user.id,
        Consultation.status.in_([ConsultationStatus.ANSWERED, ConsultationStatus.RATED]),
    ]
    total = (
        await db.scalar(sa.select(sa.func.count()).select_from(Consultation).where(*conditions))
    ) or 0
    rows = (
        await db.scalars(
            sa.select(Consultation)
            .where(*conditions)
            .order_by(Consultation.answered_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
    ).all()
    return Page(
        items=[await _list_item(db, c) for c in rows],
        total=total,
        limit=page.limit,
        offset=page.offset,
    )


@router.get("/{consultation_id}", response_model=ConsultationResponse)
async def get_consultation(
    consultation_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> ConsultationResponse:
    consultation = await _load_for_viewer(db, consultation_id, user)
    return await _response(db, consultation, viewer=user)


@router.post("/{consultation_id}/claim", response_model=ConsultationResponse)
async def claim_consultation(
    consultation_id: uuid.UUID, db: DbSession, user: VerifiedDoctor
) -> ConsultationResponse:
    """ "Qabul qilish" — exclusive; the loser gets a 409."""
    consultation = await service.claim(db, consultation_id, user)
    await db.commit()
    await db.refresh(consultation)
    return await _response(db, consultation, viewer=user)


@router.post("/{consultation_id}/answer", response_model=ConsultationResponse)
async def answer_consultation(
    consultation_id: uuid.UUID,
    payload: ConsultationAnswerRequest,
    db: DbSession,
    user: VerifiedDoctor,
) -> ConsultationResponse:
    """Send the answer; 80% is credited to the doctor's wallet."""
    consultation = await service.answer(db, consultation_id, user, payload.answer_text)
    await db.commit()
    await db.refresh(consultation)
    return await _response(db, consultation, viewer=user)


@router.post("/{consultation_id}/rate", response_model=ConsultationResponse)
async def rate_consultation(
    consultation_id: uuid.UUID,
    payload: ConsultationRateRequest,
    db: DbSession,
    user: CurrentUser,
) -> ConsultationResponse:
    consultation = await service.rate(db, consultation_id, user, payload.rating, payload.review)
    await db.commit()
    await db.refresh(consultation)
    return await _response(db, consultation, viewer=user)


# --------------------------------------------------------------------- helpers
async def _load_for_viewer(db: DbSession, consultation_id: uuid.UUID, user: User) -> Consultation:
    consultation = await db.get(Consultation, consultation_id)
    if consultation is None:
        raise NotFoundError("consultation not found", code="consultation_not_found")

    if consultation.patient_user_id == user.id:
        return consultation
    if consultation.doctor_user_id == user.id:
        return consultation

    # An unclaimed matched request is visible to any doctor who could take it.
    if (
        consultation.status == ConsultationStatus.OPEN
        and consultation.targeting == ConsultationTargeting.MATCHED
    ):
        profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
        if profile is not None and consultation.specialty in profile.specialties():
            return consultation

    raise ForbiddenError("not your consultation", code="not_yours")


async def _response(
    db: DbSession, consultation: Consultation, *, viewer: User
) -> ConsultationResponse:
    response = ConsultationResponse.model_validate(consultation)

    if consultation.doctor_user_id:
        profile = await db.scalar(
            sa.select(DoctorProfile).where(DoctorProfile.user_id == consultation.doctor_user_id)
        )
        if profile is not None:
            response.doctor_name = profile.full_name
            response.doctor_specialty = profile.specialty
            response.doctor_rating = profile.rating_average

    is_patient = consultation.patient_user_id == viewer.id
    if is_patient:
        response.patient_name = viewer.full_name
    else:
        patient = await db.get(User, consultation.patient_user_id)
        response.patient_name = service.display_name_for_doctor(
            consultation, patient.full_name if patient else None
        )
        # The frozen clinical snapshot is only opened once the doctor has taken
        # the request — before that they are choosing a question, not a patient.
        if consultation.status == ConsultationStatus.OPEN:
            response.snapshot = None
            return response

    response.snapshot = ConsultationSnapshotView(**(consultation.snapshot or {}))
    return response


async def _list_item(db: DbSession, consultation: Consultation) -> ConsultationListItem:
    patient = await db.get(User, consultation.patient_user_id)
    question = consultation.question
    return ConsultationListItem(
        id=consultation.id,
        status=consultation.status,
        specialty=consultation.specialty,
        display_name=service.display_name_for_doctor(
            consultation, patient.full_name if patient else None
        ),
        question_preview=question[:160] + ("…" if len(question) > 160 else ""),
        price_uzs=consultation.price_uzs,
        created_at=consultation.created_at,
        sla_expires_at=consultation.sla_expires_at,
        rating=consultation.rating,
        answered_at=consultation.answered_at,
    )
