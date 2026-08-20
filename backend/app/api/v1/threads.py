"""Care-thread endpoints — the clinical surface for both roles.

Every handler resolves the thread through :mod:`app.services.access` first, so
the isolation rule of spec 2.2 is applied uniformly: a doctor only ever reaches
their own thread with a patient, and never another doctor's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import sqlalchemy as sa
from fastapi import APIRouter, Query, Response, UploadFile, status

from app.api.deps import CurrentUser, DbSession
from app.core.errors import ForbiddenError, NotFoundError, ValidationError
from app.models.care import (
    CareThread,
    CheckinSubmission,
    Diagnosis,
    DiagnosisChangeRequest,
    Document,
    Medication,
    MedicationDose,
    MetricReading,
    MetricSeries,
)
from app.models.enums import (
    ChangeRequestStatus,
    DiagnosisStatus,
    DocumentPurpose,
    DoseConfirmationChannel,
    ReadingSource,
    UserRole,
)
from app.models.profile import DoctorProfile
from app.models.template import DiagnosisTemplate
from app.models.user import User
from app.schemas.care import (
    CareThreadSummary,
    CheckinQuestionView,
    CheckinResponse,
    CheckinSubmitRequest,
    ConnectByCodeRequest,
    ConnectByCodeResponse,
    DiagnosisChangeRequestCreate,
    DiagnosisChangeRequestResponse,
    DiagnosisChangeResolve,
    DiagnosisCreateRequest,
    DiagnosisResponse,
    DiagnosisTemplateResponse,
    DocumentResponse,
    DoseResponse,
    MedicationCreateRequest,
    MedicationResponse,
    MedicationUpdateRequest,
    MetricSeriesCreateRequest,
    MetricSeriesResponse,
    MetricSeriesUpdateRequest,
    ReadingCreateRequest,
    ReadingResponse,
    ShareThreadRequest,
    TemplateMatchRequest,
    TemplateMatchResponse,
    TemplateOption,
    TodayResponse,
    TrendPoint,
    TrendResponse,
)
from app.schemas.common import OkResponse
from app.services import care as care_service
from app.services import excel as excel_service
from app.services import medications as med_service
from app.services import storage
from app.services.access import (
    get_or_create_personal_thread,
    resolve_doctor_thread,
    resolve_thread,
    visible_thread_filter,
)
from app.services.templates import (
    apply_template_to_thread,
    checkin_questions_for,
    match_template,
)

router = APIRouter(prefix="/threads", tags=["care"])


# --------------------------------------------------------------------- threads
@router.get("", response_model=list[CareThreadSummary])
async def list_threads(
    db: DbSession, user: CurrentUser, include_personal: bool = True
) -> list[CareThreadSummary]:
    """ "Doktorlarim" for a patient; the roster for a doctor."""
    stmt = sa.select(CareThread).where(
        visible_thread_filter(user), CareThread.archived_at.is_(None)
    )
    if not include_personal:
        stmt = stmt.where(CareThread.doctor_user_id.is_not(None))

    threads = (
        await db.scalars(stmt.order_by(CareThread.last_activity_at.desc().nullslast()))
    ).all()
    return [await _summarize(db, thread) for thread in threads]


@router.get("/personal", response_model=CareThreadSummary)
async def get_personal_thread(db: DbSession, user: CurrentUser) -> CareThreadSummary:
    """The patient's private container, created on first use (spec 2.2)."""
    if user.role != UserRole.PATIENT:
        raise ForbiddenError("patient role required", code="patient_role_required")
    thread = await get_or_create_personal_thread(db, user)
    await db.commit()
    await db.refresh(thread)
    return await _summarize(db, thread)


@router.post("/connect", response_model=ConnectByCodeResponse)
async def connect_by_code(
    payload: ConnectByCodeRequest, db: DbSession, user: CurrentUser
) -> ConnectByCodeResponse:
    """Redeem a doctor's one-time invite code or permanent connect code."""
    if user.role != UserRole.PATIENT:
        raise ForbiddenError("patient role required", code="patient_role_required")

    thread, prefilled = await care_service.redeem_code(db, patient=user, code=payload.code)
    await db.commit()
    await db.refresh(thread)

    diagnosis = await db.scalar(
        sa.select(Diagnosis)
        .where(Diagnosis.care_thread_id == thread.id, Diagnosis.is_active.is_(True))
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )
    return ConnectByCodeResponse(
        thread=await _summarize(db, thread),
        prefilled=prefilled,
        prefilled_name=user.full_name,
        prefilled_diagnosis=diagnosis.text if diagnosis else None,
    )


@router.post("/{thread_id}/share-personal", response_model=OkResponse)
async def share_personal(
    thread_id: uuid.UUID, payload: ShareThreadRequest, db: DbSession, user: CurrentUser
) -> OkResponse:
    """Consent dialog: copy the personal container into this doctor's thread."""
    access = await resolve_thread(db, thread_id, user)
    access.require_patient()
    if not payload.consent:
        raise ValidationError("consent is required", code="consent_required")

    copied = await care_service.share_personal_thread(
        db, patient=user, source_thread_id=payload.source_thread_id, target_thread_id=thread_id
    )
    await db.commit()
    return OkResponse(ok=copied >= 0)


@router.get("/{thread_id}", response_model=CareThreadSummary)
async def get_thread(thread_id: uuid.UUID, db: DbSession, user: CurrentUser) -> CareThreadSummary:
    access = await resolve_thread(db, thread_id, user)
    return await _summarize(db, access.thread)


# ------------------------------------------------------------------- diagnoses
@router.get("/{thread_id}/diagnoses", response_model=list[DiagnosisResponse])
async def list_diagnoses(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[DiagnosisResponse]:
    access = await resolve_thread(db, thread_id, user)
    diagnoses = (
        await db.scalars(
            sa.select(Diagnosis)
            .where(Diagnosis.care_thread_id == access.thread_id)
            .order_by(Diagnosis.created_at.desc())
        )
    ).all()
    return [await _diagnosis_response(db, d, user.locale) for d in diagnoses]


@router.post(
    "/{thread_id}/diagnoses", response_model=DiagnosisResponse, status_code=status.HTTP_201_CREATED
)
async def create_diagnosis(
    thread_id: uuid.UUID,
    payload: DiagnosisCreateRequest,
    db: DbSession,
    user: CurrentUser,
) -> DiagnosisResponse:
    """Add a diagnosis.

    A doctor's entry is verified immediately; a patient's is unverified until the
    doctor confirms it (spec 2.3).
    """
    access = await resolve_thread(db, thread_id, user)
    template = await db.get(DiagnosisTemplate, payload.template_id) if payload.template_id else None
    if payload.template_id and template is None:
        raise NotFoundError("template not found", code="template_not_found")

    diagnosis = await care_service.create_diagnosis(
        db,
        thread=access.thread,
        author=user,
        text=payload.text,
        template=template,
        status=DiagnosisStatus.VERIFIED if access.is_doctor else DiagnosisStatus.UNVERIFIED,
        notes=payload.notes,
        auto_match=payload.auto_match_template,
    )
    await db.commit()
    await db.refresh(diagnosis)
    return await _diagnosis_response(db, diagnosis, user.locale)


@router.patch("/{thread_id}/diagnoses/{diagnosis_id}", response_model=DiagnosisResponse)
async def update_diagnosis(
    thread_id: uuid.UUID,
    diagnosis_id: uuid.UUID,
    payload: DiagnosisCreateRequest,
    db: DbSession,
    user: CurrentUser,
) -> DiagnosisResponse:
    """Edit a diagnosis. A patient cannot touch a verified one (spec 2.3)."""
    access = await resolve_thread(db, thread_id, user)
    diagnosis = await _load_diagnosis(db, diagnosis_id, access.thread_id)

    if access.is_patient:
        care_service.assert_patient_may_edit(diagnosis)

    diagnosis.text = payload.text.strip()
    if payload.notes is not None:
        diagnosis.notes = payload.notes
    if payload.template_id is not None:
        template = await db.get(DiagnosisTemplate, payload.template_id)
        if template is None:
            raise NotFoundError("template not found", code="template_not_found")
        diagnosis.template_id = template.id
        if diagnosis.status == DiagnosisStatus.VERIFIED:
            await apply_template_to_thread(db, access.thread_id, template)

    if access.is_doctor:
        await care_service.verify_diagnosis(db, diagnosis, user)

    await db.commit()
    await db.refresh(diagnosis)
    return await _diagnosis_response(db, diagnosis, user.locale)


@router.post("/{thread_id}/diagnoses/{diagnosis_id}/verify", response_model=DiagnosisResponse)
async def verify_diagnosis(
    thread_id: uuid.UUID, diagnosis_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> DiagnosisResponse:
    access = await resolve_doctor_thread(db, thread_id, user)
    diagnosis = await _load_diagnosis(db, diagnosis_id, access.thread_id)
    await care_service.verify_diagnosis(db, diagnosis, user)
    await db.commit()
    await db.refresh(diagnosis)
    return await _diagnosis_response(db, diagnosis, user.locale)


@router.post(
    "/{thread_id}/diagnoses/{diagnosis_id}/change-requests",
    response_model=DiagnosisChangeRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_diagnosis_change(
    thread_id: uuid.UUID,
    diagnosis_id: uuid.UUID,
    payload: DiagnosisChangeRequestCreate,
    db: DbSession,
    user: CurrentUser,
) -> DiagnosisChangeRequestResponse:
    """ "O'zgartirish taklif qilish" — the patient's only route to a verified record."""
    access = await resolve_thread(db, thread_id, user)
    access.require_patient()
    diagnosis = await _load_diagnosis(db, diagnosis_id, access.thread_id)

    request = await care_service.create_change_request(
        db,
        diagnosis=diagnosis,
        patient=user,
        comment=payload.comment,
        proposed_text=payload.proposed_text,
    )
    await db.commit()
    await db.refresh(request)
    return DiagnosisChangeRequestResponse.model_validate(request)


@router.post(
    "/{thread_id}/change-requests/{request_id}/resolve",
    response_model=DiagnosisChangeRequestResponse,
)
async def resolve_change_request(
    thread_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: DiagnosisChangeResolve,
    db: DbSession,
    user: CurrentUser,
) -> DiagnosisChangeRequestResponse:
    access = await resolve_doctor_thread(db, thread_id, user)
    request = await db.get(DiagnosisChangeRequest, request_id)
    if request is None:
        raise NotFoundError("change request not found", code="change_request_not_found")

    diagnosis = await _load_diagnosis(db, request.diagnosis_id, access.thread_id)
    if diagnosis.care_thread_id != access.thread_id:
        raise NotFoundError("change request not found", code="change_request_not_found")

    await care_service.resolve_change_request(
        db,
        request=request,
        doctor=user,
        accept=payload.accept,
        resolution_note=payload.resolution_note,
        final_text=payload.final_text,
    )
    await db.commit()
    await db.refresh(request)
    return DiagnosisChangeRequestResponse.model_validate(request)


# ------------------------------------------------------------------- templates
@router.get("/templates/all", response_model=list[DiagnosisTemplateResponse])
async def list_templates(db: DbSession, user: CurrentUser) -> list[DiagnosisTemplateResponse]:
    templates = (
        await db.scalars(
            sa.select(DiagnosisTemplate)
            .where(DiagnosisTemplate.is_active.is_(True))
            .order_by(DiagnosisTemplate.sort_order)
        )
    ).all()
    return [DiagnosisTemplateResponse.model_validate(t) for t in templates]


@router.post("/templates/match", response_model=TemplateMatchResponse)
async def match_diagnosis_template(
    payload: TemplateMatchRequest, db: DbSession, user: CurrentUser
) -> TemplateMatchResponse:
    """Auto-select the template for a typed diagnosis (spec 6)."""
    result = await match_template(db, payload.text)
    return TemplateMatchResponse(
        template_id=result.template.id if result.template else None,
        template_name=result.template.localized_name(user.locale) if result.template else None,
        confidence=result.confidence,
        alternatives=[
            TemplateOption(
                id=template.id,
                code=template.code,
                name=template.localized_name(user.locale),
                specialty=template.specialty,
            )
            for template, _score in result.alternatives
        ],
    )


@router.post(
    "/{thread_id}/templates/{template_id}/apply", response_model=list[MetricSeriesResponse]
)
async def apply_template(
    thread_id: uuid.UUID,
    template_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    replace: bool = False,
) -> list[MetricSeriesResponse]:
    access = await resolve_doctor_thread(db, thread_id, user)
    template = await db.get(DiagnosisTemplate, template_id)
    if template is None:
        raise NotFoundError("template not found", code="template_not_found")

    series_list = await apply_template_to_thread(db, access.thread_id, template, replace=replace)
    await db.commit()
    return [MetricSeriesResponse.model_validate(s) for s in series_list]


# ----------------------------------------------------------------- medications
@router.get("/{thread_id}/medications", response_model=list[MedicationResponse])
async def list_medications(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser, active_only: bool = True
) -> list[MedicationResponse]:
    access = await resolve_thread(db, thread_id, user)
    stmt = sa.select(Medication).where(Medication.care_thread_id == access.thread_id)
    if active_only:
        stmt = stmt.where(Medication.is_active.is_(True))

    medications = (await db.scalars(stmt.order_by(Medication.created_at))).all()
    result = []
    for medication in medications:
        response = MedicationResponse.model_validate(medication)
        response.adherence_7d = await med_service.adherence_percent(
            db, access.thread_id, medication_id=medication.id
        )
        result.append(response)
    return result


@router.post(
    "/{thread_id}/medications",
    response_model=MedicationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_medication(
    thread_id: uuid.UUID,
    payload: MedicationCreateRequest,
    db: DbSession,
    user: CurrentUser,
) -> MedicationResponse:
    access = await resolve_thread(db, thread_id, user)
    # In a doctor thread the prescription is the doctor's; the patient may only
    # keep medications in their own personal container.
    if access.is_patient and not access.thread.is_personal:
        raise ForbiddenError("only your doctor can change the prescription", code="doctor_only")

    medication = Medication(
        care_thread_id=access.thread_id,
        name=payload.name.strip(),
        dose=payload.dose.strip(),
        instructions=payload.instructions,
        times=payload.times,
        weekdays=payload.weekdays,
        starts_on=payload.starts_on or med_service.local_today(),
        ends_on=payload.ends_on,
        created_by_user_id=user.id,
    )
    db.add(medication)
    await db.flush()
    await med_service.materialize_doses(db, medication)
    access.thread.last_activity_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(medication)
    return MedicationResponse.model_validate(medication)


@router.patch("/{thread_id}/medications/{medication_id}", response_model=MedicationResponse)
async def update_medication(
    thread_id: uuid.UUID,
    medication_id: uuid.UUID,
    payload: MedicationUpdateRequest,
    db: DbSession,
    user: CurrentUser,
) -> MedicationResponse:
    access = await resolve_thread(db, thread_id, user)
    if access.is_patient and not access.thread.is_personal:
        raise ForbiddenError("only your doctor can change the prescription", code="doctor_only")

    medication = await db.get(Medication, medication_id)
    if medication is None or medication.care_thread_id != access.thread_id:
        raise NotFoundError("medication not found", code="medication_not_found")

    data = payload.model_dump(exclude_unset=True)
    schedule_changed = any(k in data for k in ("times", "weekdays", "ends_on", "is_active"))
    for field, value in data.items():
        setattr(medication, field, value)
    await db.flush()
    if schedule_changed:
        await med_service.resync_medication(db, medication)

    await db.commit()
    await db.refresh(medication)
    return MedicationResponse.model_validate(medication)


@router.delete("/{thread_id}/medications/{medication_id}", response_model=OkResponse)
async def delete_medication(
    thread_id: uuid.UUID, medication_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> OkResponse:
    access = await resolve_thread(db, thread_id, user)
    if access.is_patient and not access.thread.is_personal:
        raise ForbiddenError("only your doctor can change the prescription", code="doctor_only")

    medication = await db.get(Medication, medication_id)
    if medication is None or medication.care_thread_id != access.thread_id:
        raise NotFoundError("medication not found", code="medication_not_found")

    # Deactivated rather than deleted: the intake history stays auditable.
    medication.is_active = False
    await db.flush()
    await med_service.resync_medication(db, medication)
    await db.commit()
    return OkResponse()


@router.get("/{thread_id}/doses", response_model=list[DoseResponse])
async def list_doses(
    thread_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    day: date | None = Query(default=None),
) -> list[DoseResponse]:
    access = await resolve_thread(db, thread_id, user)
    doses = await med_service.doses_for_day(db, access.thread_id, day)
    return await _dose_responses(db, doses)


@router.post("/{thread_id}/doses/{dose_id}/taken", response_model=DoseResponse)
async def mark_dose_taken(
    thread_id: uuid.UUID, dose_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> DoseResponse:
    """The "Ichdim ✓" button."""
    access = await resolve_thread(db, thread_id, user)
    dose = await db.get(MedicationDose, dose_id)
    if dose is None or dose.care_thread_id != access.thread_id:
        raise NotFoundError("dose not found", code="dose_not_found")

    channel = DoseConfirmationChannel.DOCTOR if access.is_doctor else DoseConfirmationChannel.APP
    await med_service.mark_dose(db, dose, taken=True, channel=channel)
    access.thread.last_activity_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(dose)
    return (await _dose_responses(db, [dose]))[0]


# --------------------------------------------------------------------- metrics
@router.get("/{thread_id}/series", response_model=list[MetricSeriesResponse])
async def list_series(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[MetricSeriesResponse]:
    """The swipeable trend cards."""
    access = await resolve_thread(db, thread_id, user)
    series_list = (
        await db.scalars(
            sa.select(MetricSeries)
            .where(
                MetricSeries.care_thread_id == access.thread_id,
                MetricSeries.is_active.is_(True),
            )
            .order_by(MetricSeries.sort_order)
        )
    ).all()

    result = []
    for series in series_list:
        response = MetricSeriesResponse.model_validate(series)
        latest = await db.scalar(
            sa.select(MetricReading)
            .where(MetricReading.series_id == series.id)
            .order_by(MetricReading.recorded_at.desc())
            .limit(1)
        )
        if latest is not None:
            response.latest_value = latest.value
            response.latest_recorded_at = latest.recorded_at
        result.append(response)
    return result


@router.post(
    "/{thread_id}/series", response_model=MetricSeriesResponse, status_code=status.HTTP_201_CREATED
)
async def create_series(
    thread_id: uuid.UUID,
    payload: MetricSeriesCreateRequest,
    db: DbSession,
    user: CurrentUser,
) -> MetricSeriesResponse:
    access = await resolve_thread(db, thread_id, user)
    if access.is_patient and not access.thread.is_personal:
        raise ForbiddenError("only your doctor can add indicators", code="doctor_only")

    exists = await db.scalar(
        sa.select(MetricSeries.id).where(
            MetricSeries.care_thread_id == access.thread_id, MetricSeries.key == payload.key
        )
    )
    if exists:
        raise ValidationError("this indicator already exists", code="series_exists")

    series = MetricSeries(care_thread_id=access.thread_id, **payload.model_dump())
    db.add(series)
    await db.commit()
    await db.refresh(series)
    return MetricSeriesResponse.model_validate(series)


@router.patch("/{thread_id}/series/{series_id}", response_model=MetricSeriesResponse)
async def update_series(
    thread_id: uuid.UUID,
    series_id: uuid.UUID,
    payload: MetricSeriesUpdateRequest,
    db: DbSession,
    user: CurrentUser,
) -> MetricSeriesResponse:
    access = await resolve_doctor_thread(db, thread_id, user)
    series = await _load_series(db, series_id, access.thread_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(series, field, value)
    await db.commit()
    await db.refresh(series)
    return MetricSeriesResponse.model_validate(series)


@router.post(
    "/{thread_id}/series/{series_id}/readings",
    response_model=ReadingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_reading(
    thread_id: uuid.UUID,
    series_id: uuid.UUID,
    payload: ReadingCreateRequest,
    db: DbSession,
    user: CurrentUser,
) -> ReadingResponse:
    access = await resolve_thread(db, thread_id, user)
    series = await _load_series(db, series_id, access.thread_id)

    reading = MetricReading(
        series_id=series.id,
        care_thread_id=access.thread_id,
        value=payload.value,
        value_secondary=payload.value_secondary,
        recorded_at=payload.recorded_at or datetime.now(UTC),
        source=ReadingSource.DOCTOR if access.is_doctor else ReadingSource.PATIENT,
        note=payload.note,
        recorded_by_user_id=user.id,
    )
    db.add(reading)
    access.thread.last_activity_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(reading)
    return ReadingResponse.model_validate(reading)


@router.get("/{thread_id}/series/{series_id}/trend", response_model=TrendResponse)
async def get_trend(
    thread_id: uuid.UUID,
    series_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    days: int = Query(default=30, ge=1, le=365),
) -> TrendResponse:
    access = await resolve_thread(db, thread_id, user)
    series = await _load_series(db, series_id, access.thread_id)

    since = datetime.now(UTC) - timedelta(days=days)
    readings = (
        await db.scalars(
            sa.select(MetricReading)
            .where(MetricReading.series_id == series.id, MetricReading.recorded_at >= since)
            .order_by(MetricReading.recorded_at)
        )
    ).all()

    values = [r.value for r in readings]
    in_target = None
    if values and (series.target_min is not None or series.target_max is not None):
        inside = sum(
            1
            for v in values
            if (series.target_min is None or v >= series.target_min)
            and (series.target_max is None or v <= series.target_max)
        )
        in_target = round(inside * 100.0 / len(values), 1)

    return TrendResponse(
        series=MetricSeriesResponse.model_validate(series),
        points=[
            TrendPoint(at=r.recorded_at, value=r.value, value_secondary=r.value_secondary)
            for r in readings
        ],
        average=round(sum(values) / len(values), series.decimals or 1) if values else None,
        minimum=min(values) if values else None,
        maximum=max(values) if values else None,
        in_target_percent=in_target,
    )


@router.get("/{thread_id}/series/{series_id}/export")
async def export_series(
    thread_id: uuid.UUID,
    series_id: uuid.UUID,
    db: DbSession,
    user: CurrentUser,
    days: int = Query(default=180, ge=1, le=1095),
) -> Response:
    """ "Excel'ga eksport" — available to both roles."""
    access = await resolve_thread(db, thread_id, user)
    series = await _load_series(db, series_id, access.thread_id)

    since = datetime.now(UTC) - timedelta(days=days)
    readings = list(
        (
            await db.scalars(
                sa.select(MetricReading)
                .where(MetricReading.series_id == series.id, MetricReading.recorded_at >= since)
                .order_by(MetricReading.recorded_at)
            )
        ).all()
    )
    content = excel_service.export_series(series, readings, locale=user.locale)
    filename = f"{series.key}-{datetime.now(UTC).date().isoformat()}.xlsx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{thread_id}/series/{series_id}/import", response_model=dict)
async def import_series(
    thread_id: uuid.UUID,
    series_id: uuid.UUID,
    file: UploadFile,
    db: DbSession,
    user: CurrentUser,
) -> dict:
    """ "Excel'dan import" — doctor only (spec 5.2 tab 2)."""
    access = await resolve_doctor_thread(db, thread_id, user)
    series = await _load_series(db, series_id, access.thread_id)

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise ValidationError("file too large", code="file_too_large")

    result = excel_service.parse_series_workbook(content)
    for row in result.rows:
        db.add(
            MetricReading(
                series_id=series.id,
                care_thread_id=access.thread_id,
                value=row.value,
                value_secondary=row.value_secondary,
                recorded_at=row.recorded_at,
                source=ReadingSource.IMPORT,
                note=row.note,
                recorded_by_user_id=user.id,
            )
        )
    await db.commit()
    return {
        "imported": len(result.rows),
        "skipped": result.skipped,
        "errors": result.errors[:20],
    }


# -------------------------------------------------------------------- check-in
@router.get("/{thread_id}/today", response_model=TodayResponse)
async def get_today(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser, slot: str = "day"
) -> TodayResponse:
    """Everything the "Bugun" tab renders for this thread."""
    access = await resolve_thread(db, thread_id, user)
    today = med_service.local_today()

    diagnosis = await db.scalar(
        sa.select(Diagnosis)
        .where(
            Diagnosis.care_thread_id == access.thread_id,
            Diagnosis.is_active.is_(True),
            Diagnosis.template_id.is_not(None),
        )
        .order_by(Diagnosis.status.desc(), Diagnosis.created_at.desc())
        .limit(1)
    )
    template = await db.get(DiagnosisTemplate, diagnosis.template_id) if diagnosis else None
    questions = [
        CheckinQuestionView(
            key=q["key"],
            prompt=q.get("prompt", {}),
            type=q.get("type", "number"),
            unit=q.get("unit"),
            metric_key=q.get("metric_key"),
            options=q.get("options", []),
            required=q.get("required", True),
        )
        for q in checkin_questions_for(template, slot=slot)
    ]

    submission = await db.scalar(
        sa.select(CheckinSubmission).where(
            CheckinSubmission.care_thread_id == access.thread_id,
            CheckinSubmission.local_date == today,
            CheckinSubmission.slot == slot,
        )
    )
    doses = await med_service.doses_for_day(db, access.thread_id, today)

    return TodayResponse(
        care_thread_id=access.thread_id,
        local_date=today,
        questions=questions,
        already_submitted=submission is not None,
        submitted_answers=submission.answers if submission else {},
        doses=await _dose_responses(db, doses),
    )


@router.post(
    "/{thread_id}/checkins", response_model=CheckinResponse, status_code=status.HTTP_201_CREATED
)
async def submit_checkin(
    thread_id: uuid.UUID,
    payload: CheckinSubmitRequest,
    db: DbSession,
    user: CurrentUser,
) -> CheckinResponse:
    """The "Belgilash" button.

    Answers tied to a metric are also written as readings, so the trend chart
    updates from the same action.
    """
    access = await resolve_thread(db, thread_id, user)
    access.require_patient()

    local_date = payload.local_date or med_service.local_today()
    now = datetime.now(UTC)

    submission = await db.scalar(
        sa.select(CheckinSubmission).where(
            CheckinSubmission.care_thread_id == access.thread_id,
            CheckinSubmission.local_date == local_date,
            CheckinSubmission.slot == payload.slot,
        )
    )
    if submission is None:
        submission = CheckinSubmission(
            care_thread_id=access.thread_id,
            local_date=local_date,
            slot=payload.slot,
            answers=payload.answers,
            submitted_at=now,
        )
        db.add(submission)
    else:
        submission.answers = {**(submission.answers or {}), **payload.answers}
        submission.submitted_at = now

    await _record_metric_answers(db, access.thread_id, payload.answers, user, now)
    access.thread.last_activity_at = now
    await db.commit()
    await db.refresh(submission)
    return CheckinResponse.model_validate(submission)


async def _record_metric_answers(
    db: DbSession, thread_id: uuid.UUID, answers: dict, user: User, when: datetime
) -> None:
    """Turn check-in answers into readings on the matching series."""
    diagnosis = await db.scalar(
        sa.select(Diagnosis)
        .where(
            Diagnosis.care_thread_id == thread_id,
            Diagnosis.is_active.is_(True),
            Diagnosis.template_id.is_not(None),
        )
        .order_by(Diagnosis.status.desc(), Diagnosis.created_at.desc())
        .limit(1)
    )
    if diagnosis is None:
        return
    template = await db.get(DiagnosisTemplate, diagnosis.template_id)
    if template is None:
        return

    question_metrics = {
        q["key"]: q.get("metric_key")
        for q in (template.checkin_questions or [])
        if q.get("metric_key")
    }
    if not question_metrics:
        return

    series_by_key = {
        series.key: series
        for series in (
            await db.scalars(
                sa.select(MetricSeries).where(MetricSeries.care_thread_id == thread_id)
            )
        ).all()
    }

    for question_key, value in answers.items():
        metric_key = question_metrics.get(question_key)
        series = series_by_key.get(metric_key) if metric_key else None
        if series is None:
            continue

        primary, secondary = _coerce_reading(value)
        if primary is None:
            continue
        db.add(
            MetricReading(
                series_id=series.id,
                care_thread_id=thread_id,
                value=primary,
                value_secondary=secondary,
                recorded_at=when,
                source=ReadingSource.PATIENT,
                recorded_by_user_id=user.id,
            )
        )


def _coerce_reading(value) -> tuple[float | None, float | None]:
    """Accept a number, a "120/80" string, or a {systolic, diastolic} object."""
    if isinstance(value, (int, float)):
        return float(value), None
    if isinstance(value, dict):
        primary = value.get("value", value.get("systolic"))
        secondary = value.get("value_secondary", value.get("diastolic"))
        try:
            return (
                float(primary) if primary is not None else None,
                float(secondary) if secondary is not None else None,
            )
        except (TypeError, ValueError):
            return None, None
    if isinstance(value, str) and "/" in value:
        left, _, right = value.partition("/")
        try:
            return float(left.strip()), float(right.strip())
        except ValueError:
            return None, None
    try:
        return float(value), None
    except (TypeError, ValueError):
        return None, None


# ------------------------------------------------------------------- documents
@router.get("/{thread_id}/documents", response_model=list[DocumentResponse])
async def list_documents(
    thread_id: uuid.UUID, db: DbSession, user: CurrentUser
) -> list[DocumentResponse]:
    access = await resolve_thread(db, thread_id, user)
    documents = (
        await db.scalars(
            sa.select(Document)
            .where(Document.care_thread_id == access.thread_id)
            .order_by(Document.created_at.desc())
        )
    ).all()

    result = []
    for document in documents:
        response = DocumentResponse.model_validate(document)
        response.download_url = await storage.presigned_url(
            document.storage_key, filename=document.filename
        )
        result.append(response)
    return result


@router.post(
    "/{thread_id}/documents",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    thread_id: uuid.UUID, file: UploadFile, db: DbSession, user: CurrentUser
) -> DocumentResponse:
    access = await resolve_thread(db, thread_id, user)
    content = await file.read()
    content_type = file.content_type or "application/octet-stream"
    storage.validate_upload(content_type, len(content))

    key = storage.build_key(
        DocumentPurpose.CARE_THREAD.value, user.id, file.filename or "file", content_type
    )
    stored = await storage.upload(content, key, content_type)
    document = Document(
        owner_user_id=user.id,
        care_thread_id=access.thread_id,
        purpose=DocumentPurpose.CARE_THREAD.value,
        storage_key=stored.key,
        filename=(file.filename or "file")[:255],
        content_type=content_type,
        size_bytes=stored.size,
        checksum=stored.checksum,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    response = DocumentResponse.model_validate(document)
    response.download_url = await storage.presigned_url(
        document.storage_key, filename=document.filename
    )
    return response


# --------------------------------------------------------------------- helpers
async def _summarize(db: DbSession, thread: CareThread) -> CareThreadSummary:
    summary = CareThreadSummary.model_validate(thread)

    if thread.doctor_user_id:
        profile = await db.scalar(
            sa.select(DoctorProfile).where(DoctorProfile.user_id == thread.doctor_user_id)
        )
        if profile is not None:
            summary.doctor_name = profile.full_name
            summary.doctor_specialty = profile.specialty
            summary.doctor_rating = profile.rating_average

    patient = await db.get(User, thread.patient_user_id)
    if patient is not None:
        summary.patient_name = patient.full_name

    diagnosis = await db.scalar(
        sa.select(Diagnosis)
        .where(Diagnosis.care_thread_id == thread.id, Diagnosis.is_active.is_(True))
        .order_by(Diagnosis.created_at.desc())
        .limit(1)
    )
    if diagnosis is not None:
        summary.primary_diagnosis = diagnosis.text
        summary.diagnosis_status = diagnosis.status
    return summary


async def _diagnosis_response(
    db: DbSession, diagnosis: Diagnosis, locale: str
) -> DiagnosisResponse:
    response = DiagnosisResponse.model_validate(diagnosis)
    if diagnosis.template_id:
        template = await db.get(DiagnosisTemplate, diagnosis.template_id)
        if template is not None:
            response.template_name = template.localized_name(locale)

    pending = await db.scalar(
        sa.select(DiagnosisChangeRequest)
        .where(
            DiagnosisChangeRequest.diagnosis_id == diagnosis.id,
            DiagnosisChangeRequest.status == ChangeRequestStatus.PENDING,
        )
        .limit(1)
    )
    if pending is not None:
        response.pending_change_request = DiagnosisChangeRequestResponse.model_validate(pending)
    return response


async def _dose_responses(db: DbSession, doses: list[MedicationDose]) -> list[DoseResponse]:
    if not doses:
        return []
    medications = {
        medication.id: medication
        for medication in (
            await db.scalars(
                sa.select(Medication).where(Medication.id.in_([d.medication_id for d in doses]))
            )
        ).all()
    }
    result = []
    for dose in doses:
        response = DoseResponse.model_validate(dose)
        medication = medications.get(dose.medication_id)
        if medication is not None:
            response.medication_name = medication.name
            response.dose_text = medication.dose
        if dose.confirmed_via is not None:
            response.confirmed_via = dose.confirmed_via.value
        result.append(response)
    return result


async def _load_diagnosis(
    db: DbSession, diagnosis_id: uuid.UUID, thread_id: uuid.UUID
) -> Diagnosis:
    diagnosis = await db.get(Diagnosis, diagnosis_id)
    # Checking thread ownership here is what stops an id from another thread
    # being used to read or edit across the isolation boundary.
    if diagnosis is None or diagnosis.care_thread_id != thread_id:
        raise NotFoundError("diagnosis not found", code="diagnosis_not_found")
    return diagnosis


async def _load_series(db: DbSession, series_id: uuid.UUID, thread_id: uuid.UUID) -> MetricSeries:
    series = await db.get(MetricSeries, series_id)
    if series is None or series.care_thread_id != thread_id:
        raise NotFoundError("indicator not found", code="series_not_found")
    return series
