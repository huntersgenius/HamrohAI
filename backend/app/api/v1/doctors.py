"""Doctor registration, profile, settings and patient roster (spec 4)."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Query, status

from app.api.deps import (
    CurrentUser,
    DbSession,
    DoctorUser,
    Pagination,
    SubscribedDoctor,
    VerifiedDoctor,
)
from app.catalog.specialties import SPECIALTIES, recommended_price
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.i18n import translate
from app.models.ai import AiEscalation
from app.models.care import CareThread, Diagnosis, Document, PatientInvite
from app.models.enums import CareThreadKind, DocumentPurpose, InviteStatus
from app.models.profile import DoctorProfile, DoctorSubscription
from app.models.user import User
from app.schemas.care import (
    PatientInviteCreateRequest,
    PatientInviteResponse,
    PatientListItem,
)
from app.schemas.common import OkResponse, Page
from app.schemas.doctor import (
    ConsultationSettingsRequest,
    DoctorProfileResponse,
    DoctorProfileUpdateRequest,
    DoctorRegisterRequest,
    DoctorSearchItem,
    DoctorSubscriptionResponse,
    SpecialtyOption,
)
from app.services import care as care_service
from app.services.billing import start_trial, subscription_is_active

router = APIRouter(prefix="/doctors", tags=["doctors"])


@router.get("/specialties", response_model=list[SpecialtyOption])
async def list_specialties() -> list[SpecialtyOption]:
    """The extendable specialty list used by the registration dropdown."""
    return [SpecialtyOption(**spec) for spec in SPECIALTIES]


@router.post("/register", response_model=DoctorProfileResponse, status_code=status.HTTP_201_CREATED)
async def register_doctor(
    payload: DoctorRegisterRequest, db: DbSession, user: DoctorUser
) -> DoctorProfileResponse:
    """Submit the registration form (spec 4.1).

    The profile is created in "tekshiruv kutilmoqda"; approval happens manually
    in the database during the MVP — there is no in-app approval screen.
    """
    existing = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
    if existing is not None:
        raise ConflictError("doctor profile already exists", code="profile_exists")

    document = await db.get(Document, payload.license_document_id)
    if document is None or document.owner_user_id != user.id:
        raise NotFoundError("licence document not found", code="document_not_found")
    if document.purpose != DocumentPurpose.DOCTOR_LICENSE:
        raise ValidationError("document is not a licence upload", code="document_wrong_purpose")

    profile = DoctorProfile(
        user_id=user.id,
        full_name=payload.full_name.strip(),
        age=payload.age,
        specialty=payload.specialty,
        experience_years=payload.experience_years,
        bio=payload.bio,
        workplace=payload.workplace,
        connect_code=await care_service.allocate_connect_code(db),
        consultation_price_uzs=recommended_price(payload.specialty),
    )
    db.add(profile)
    await db.flush()
    await start_trial(db, profile)

    if not user.full_name:
        user.full_name = profile.full_name
    await db.commit()
    await db.refresh(profile)
    return await _profile_response(db, profile)


@router.get("/me", response_model=DoctorProfileResponse)
async def get_my_profile(db: DbSession, user: DoctorUser) -> DoctorProfileResponse:
    profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
    if profile is None:
        raise NotFoundError("doctor profile not found", code="profile_not_found")
    return await _profile_response(db, profile)


@router.patch("/me", response_model=DoctorProfileResponse)
async def update_my_profile(
    payload: DoctorProfileUpdateRequest, db: DbSession, user: DoctorUser
) -> DoctorProfileResponse:
    profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
    if profile is None:
        raise NotFoundError("doctor profile not found", code="profile_not_found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    return await _profile_response(db, profile)


@router.patch("/me/consultation-settings", response_model=DoctorProfileResponse)
async def update_consultation_settings(
    payload: ConsultationSettingsRequest, db: DbSession, user: VerifiedDoctor
) -> DoctorProfileResponse:
    """Availability toggle, extra specialties and custom price (spec 4.2 tab 4)."""
    profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
    if profile is None:
        raise NotFoundError("doctor profile not found", code="profile_not_found")

    data = payload.model_dump(exclude_unset=True)
    if "consultation_specialties" in data:
        known = {spec["code"] for spec in SPECIALTIES}
        unknown = [s for s in data["consultation_specialties"] if s not in known]
        if unknown:
            raise ValidationError(
                "unknown specialty", code="specialty_unknown", details={"unknown": unknown}
            )
    for field, value in data.items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    return await _profile_response(db, profile)


@router.get("/me/connect-code", response_model=dict)
async def get_connect_code(db: DbSession, user: VerifiedDoctor) -> dict:
    """The permanent code patients enter to connect themselves."""
    profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
    if profile is None:
        raise NotFoundError("doctor profile not found", code="profile_not_found")
    return {"code": profile.connect_code}


# ---------------------------------------------------------------- patient list
@router.get("/me/patients", response_model=Page[PatientListItem])
async def list_patients(
    db: DbSession,
    user: VerifiedDoctor,
    page: Pagination,
    search: str | None = Query(default=None, max_length=120),
) -> Page[PatientListItem]:
    """The "Bemorlarim" list: connected patients plus not-yet-redeemed invites."""
    conditions = [CareThread.doctor_user_id == user.id, CareThread.archived_at.is_(None)]

    stmt = (
        sa.select(CareThread, User)
        .join(User, User.id == CareThread.patient_user_id)
        .where(*conditions)
    )
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(sa.or_(User.full_name.ilike(pattern), User.phone.ilike(pattern)))

    total = (
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(CareThread)
            .join(User, User.id == CareThread.patient_user_id)
            .where(*conditions)
        )
    ) or 0

    rows = (
        await db.execute(
            stmt.order_by(CareThread.last_activity_at.desc().nullslast())
            .limit(page.limit)
            .offset(page.offset)
        )
    ).all()

    items: list[PatientListItem] = []
    for thread, patient in rows:
        diagnosis = await db.scalar(
            sa.select(Diagnosis)
            .where(Diagnosis.care_thread_id == thread.id, Diagnosis.is_active.is_(True))
            .order_by(Diagnosis.created_at.desc())
            .limit(1)
        )
        risk_level, reasons = await care_service.compute_risk(db, thread.id)
        open_escalations = (
            await db.scalar(
                sa.select(sa.func.count())
                .select_from(AiEscalation)
                .where(AiEscalation.care_thread_id == thread.id, AiEscalation.is_open.is_(True))
            )
        ) or 0
        items.append(
            PatientListItem(
                care_thread_id=thread.id,
                patient_user_id=patient.id,
                full_name=patient.full_name or "Bemor",
                phone=patient.phone,
                primary_diagnosis=diagnosis.text if diagnosis else None,
                diagnosis_status=diagnosis.status if diagnosis else None,
                last_activity_at=thread.last_activity_at,
                risk_level=risk_level,
                risk_reasons=reasons,
                open_escalations=open_escalations,
            )
        )

    # Only on the first page: invites the patient has not redeemed yet, so the
    # doctor can see a pending client and re-share the code.
    if page.offset == 0:
        invites = (
            await db.scalars(
                sa.select(PatientInvite)
                .where(
                    PatientInvite.doctor_user_id == user.id,
                    PatientInvite.status == InviteStatus.ISSUED,
                )
                .order_by(PatientInvite.created_at.desc())
                .limit(50)
            )
        ).all()
        for invite in invites:
            items.insert(
                0,
                PatientListItem(
                    care_thread_id=invite.id,  # placeholder id; no thread exists yet
                    patient_user_id=None,
                    full_name=invite.full_name,
                    phone=invite.phone,
                    primary_diagnosis=invite.diagnosis_text,
                    is_pending_invite=True,
                    pending_invite_code=invite.code,
                ),
            )

    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


# -------------------------------------------------------------------- invites
@router.post(
    "/me/invites", response_model=PatientInviteResponse, status_code=status.HTTP_201_CREATED
)
async def create_invite(
    payload: PatientInviteCreateRequest, db: DbSession, user: SubscribedDoctor
) -> PatientInviteResponse:
    """ "Mijoz qo'shish" — save the patient and produce a one-time code."""
    for document_id in payload.document_ids:
        document = await db.get(Document, document_id)
        if document is None or document.owner_user_id != user.id:
            raise NotFoundError("document not found", code="document_not_found")

    invite, template = await care_service.create_invite(
        db,
        doctor=user,
        full_name=payload.full_name,
        phone=payload.phone,
        diagnosis_text=payload.diagnosis_text,
        template_id=payload.template_id,
        document_ids=payload.document_ids,
    )
    await db.commit()
    await db.refresh(invite)

    response = PatientInviteResponse.model_validate(invite)
    response.template_name = template.localized_name(user.locale) if template else None
    response.share_text = translate(
        "sms.invite", user.locale, code=invite.code, link="https://hamroh.uz/app"
    )
    return response


@router.get("/me/invites", response_model=list[PatientInviteResponse])
async def list_invites(db: DbSession, user: VerifiedDoctor) -> list[PatientInviteResponse]:
    invites = (
        await db.scalars(
            sa.select(PatientInvite)
            .where(PatientInvite.doctor_user_id == user.id)
            .order_by(PatientInvite.created_at.desc())
            .limit(100)
        )
    ).all()
    return [PatientInviteResponse.model_validate(invite) for invite in invites]


@router.delete("/me/invites/{invite_id}", response_model=OkResponse)
async def revoke_invite(invite_id: uuid.UUID, db: DbSession, user: VerifiedDoctor) -> OkResponse:
    invite = await db.get(PatientInvite, invite_id)
    if invite is None or invite.doctor_user_id != user.id:
        raise NotFoundError("invite not found", code="invite_not_found")
    if invite.status == InviteStatus.REDEEMED:
        raise ConflictError("this code has already been used", code="code_used")
    invite.status = InviteStatus.REVOKED
    await db.commit()
    return OkResponse()


# --------------------------------------------------------------------- search
@router.get("/search", response_model=list[DoctorSearchItem])
async def search_doctors(
    db: DbSession,
    user: CurrentUser,
    q: str | None = Query(default=None, max_length=120),
    specialty: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=20, ge=1, le=50),
) -> list[DoctorSearchItem]:
    """Find a doctor by name or specialty (spec 5.2 tab 3B).

    Only verified doctors who are open to consultations are listed.
    """
    stmt = (
        sa.select(DoctorProfile, User)
        .join(User, User.id == DoctorProfile.user_id)
        .where(
            DoctorProfile.verification_status == "approved",
            DoctorProfile.consultation_open.is_(True),
            User.is_active.is_(True),
            User.id != user.id,
        )
    )
    if q:
        stmt = stmt.where(DoctorProfile.full_name.ilike(f"%{q.strip()}%"))
    if specialty:
        stmt = stmt.where(DoctorProfile.specialty == specialty)

    rows = (
        await db.execute(
            stmt.order_by(
                (DoctorProfile.rating_sum / sa.func.nullif(DoctorProfile.rating_count, 0))
                .desc()
                .nullslast(),
                DoctorProfile.experience_years.desc(),
            ).limit(limit)
        )
    ).all()

    connected = set(
        (
            await db.scalars(
                sa.select(CareThread.doctor_user_id).where(
                    CareThread.patient_user_id == user.id,
                    CareThread.doctor_user_id.is_not(None),
                )
            )
        ).all()
    )

    return [
        DoctorSearchItem(
            user_id=profile.user_id,
            full_name=profile.full_name,
            specialty=profile.specialty,
            experience_years=profile.experience_years,
            rating_average=profile.rating_average,
            rating_count=profile.rating_count,
            consultation_price_uzs=(
                profile.consultation_price_uzs or recommended_price(profile.specialty)
            ),
            avatar_url=doctor_user.avatar_url,
            is_connected=profile.user_id in connected,
        )
        for profile, doctor_user in rows
    ]


@router.get("/{doctor_user_id}", response_model=DoctorSearchItem)
async def get_doctor(
    doctor_user_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> DoctorSearchItem:
    row = (
        await db.execute(
            sa.select(DoctorProfile, User)
            .join(User, User.id == DoctorProfile.user_id)
            .where(DoctorProfile.user_id == doctor_user_id)
        )
    ).first()
    if row is None:
        raise NotFoundError("doctor not found", code="doctor_not_found")
    profile, doctor_user = row
    if not profile.is_approved:
        raise NotFoundError("doctor not found", code="doctor_not_found")

    return DoctorSearchItem(
        user_id=profile.user_id,
        full_name=profile.full_name,
        specialty=profile.specialty,
        experience_years=profile.experience_years,
        rating_average=profile.rating_average,
        rating_count=profile.rating_count,
        consultation_price_uzs=(
            profile.consultation_price_uzs or recommended_price(profile.specialty)
        ),
        avatar_url=doctor_user.avatar_url,
    )


async def _profile_response(db: DbSession, profile: DoctorProfile) -> DoctorProfileResponse:
    patient_count = (
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(CareThread)
            .where(
                CareThread.doctor_user_id == profile.user_id,
                CareThread.kind == CareThreadKind.DOCTOR,
                CareThread.archived_at.is_(None),
            )
        )
    ) or 0

    subscription = await db.scalar(
        sa.select(DoctorSubscription).where(DoctorSubscription.doctor_profile_id == profile.id)
    )
    response = DoctorProfileResponse.model_validate(profile)
    response.rating_average = profile.rating_average
    response.patient_count = patient_count
    if subscription is not None:
        response.subscription = DoctorSubscriptionResponse(
            plan=subscription.plan.value,
            status=subscription.status,
            current_period_end=subscription.current_period_end,
            is_active=subscription_is_active(subscription),
        )
    return response
