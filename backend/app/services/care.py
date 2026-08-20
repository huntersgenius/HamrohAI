"""Care-thread lifecycle: invites, connections, diagnoses, risk scoring.

The spec's structural rules live here:

* a doctor's one-time code (spec 4.2 tab 1) pre-fills clinical data; the doctor's
  permanent code (spec 4.2 tab 4) only connects;
* redeeming either creates a *new isolated thread*, never merges into an existing
  doctor's data;
* the patient's personal container is only merged into a doctor thread after an
  explicit consent confirmation (spec 2.2);
* a verified diagnosis can never be edited by the patient (spec 2.3).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.security import generate_short_code
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
    PatientInvite,
)
from app.models.enums import (
    CareThreadKind,
    ChangeRequestStatus,
    DiagnosisStatus,
    DoseStatus,
    InviteStatus,
    NotificationType,
)
from app.models.profile import DoctorProfile
from app.models.template import DiagnosisTemplate
from app.models.user import User
from app.services.templates import apply_template_to_thread, match_template

log = get_logger(__name__)

INVITE_TTL_DAYS = 30
CODE_MAX_ATTEMPTS = 8


# ----------------------------------------------------------------- unique codes
async def _unique_code(db: AsyncSession, model, column, length: int) -> str:
    for _ in range(CODE_MAX_ATTEMPTS):
        code = generate_short_code(length)
        exists = await db.scalar(sa.select(model.id).where(column == code))
        if not exists:
            return code
    raise ConflictError("could not allocate a unique code", code="code_allocation_failed")


async def allocate_connect_code(db: AsyncSession) -> str:
    """Permanent, reusable doctor code shown in settings."""
    return await _unique_code(db, DoctorProfile, DoctorProfile.connect_code, 6)


# ---------------------------------------------------------------------- invites
async def create_invite(
    db: AsyncSession,
    *,
    doctor: User,
    full_name: str,
    phone: str,
    diagnosis_text: str | None,
    template_id: uuid.UUID | None,
    document_ids: list[uuid.UUID],
) -> tuple[PatientInvite, DiagnosisTemplate | None]:
    """ "Mijoz qo'shish" — issue a one-time code with pre-filled clinical data.

    The template is auto-matched from the diagnosis text and applied as the
    default when the doctor did not pick one explicitly (spec 6).
    """
    template: DiagnosisTemplate | None = None
    if template_id is not None:
        template = await db.get(DiagnosisTemplate, template_id)
        if template is None:
            raise NotFoundError("template not found", code="template_not_found")
    elif diagnosis_text:
        match = await match_template(db, diagnosis_text)
        template = match.template

    # A patient already connected to this doctor doesn't need a second thread.
    existing_patient = await db.scalar(sa.select(User).where(User.phone == phone))
    if existing_patient is not None:
        already = await db.scalar(
            sa.select(CareThread.id).where(
                CareThread.patient_user_id == existing_patient.id,
                CareThread.doctor_user_id == doctor.id,
            )
        )
        if already:
            raise ConflictError("this patient is already connected", code="already_connected")

    invite = PatientInvite(
        doctor_user_id=doctor.id,
        code=await _unique_code(db, PatientInvite, PatientInvite.code, 8),
        full_name=full_name.strip(),
        phone=phone,
        diagnosis_text=(diagnosis_text or "").strip() or None,
        template_id=template.id if template else None,
        expires_at=datetime.now(UTC) + timedelta(days=INVITE_TTL_DAYS),
        document_ids=[str(d) for d in document_ids],
    )
    db.add(invite)
    await db.flush()
    log.info("care.invite_created", doctor_id=str(doctor.id), invite_id=str(invite.id))
    return invite, template


async def find_invite(db: AsyncSession, code: str) -> PatientInvite | None:
    invite = await db.scalar(sa.select(PatientInvite).where(PatientInvite.code == code.upper()))
    if invite is None:
        return None
    expires = invite.expires_at
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=UTC)
    if invite.status == InviteStatus.ISSUED and expires and expires < datetime.now(UTC):
        invite.status = InviteStatus.EXPIRED
        await db.flush()
    return invite


async def redeem_code(db: AsyncSession, *, patient: User, code: str) -> tuple[CareThread, bool]:
    """Connect a patient using either code type.

    Returns ``(thread, prefilled)``; ``prefilled`` is True when a one-time invite
    supplied name/diagnosis that the patient only had to confirm.
    """
    normalized = code.strip().upper()

    invite = await find_invite(db, normalized)
    if invite is not None:
        return await _redeem_invite(db, patient=patient, invite=invite), True

    profile = await db.scalar(
        sa.select(DoctorProfile).where(DoctorProfile.connect_code == normalized)
    )
    if profile is None:
        raise NotFoundError("code not found", code="code_not_found")
    if not profile.is_approved:
        raise ValidationError("this doctor is not verified yet", code="doctor_not_verified")
    thread = await connect_to_doctor(db, patient=patient, doctor_user_id=profile.user_id)
    return thread, False


async def _redeem_invite(db: AsyncSession, *, patient: User, invite: PatientInvite) -> CareThread:
    if invite.status == InviteStatus.REDEEMED:
        raise ConflictError("this code has already been used", code="code_used")
    if invite.status in (InviteStatus.EXPIRED, InviteStatus.REVOKED):
        raise ValidationError("this code is no longer valid", code="code_expired")

    # The invite is bound to the phone number the doctor entered — the identity
    # key of the platform (spec 2.1). Anyone else must not be able to redeem it.
    if invite.phone != patient.phone:
        raise ForbiddenError(
            "this code was issued for a different phone number", code="code_phone_mismatch"
        )

    thread = await connect_to_doctor(db, patient=patient, doctor_user_id=invite.doctor_user_id)

    if invite.diagnosis_text:
        template = (
            await db.get(DiagnosisTemplate, invite.template_id) if invite.template_id else None
        )
        # Entered by the doctor, so it is verified from the start (spec 2.3).
        await create_diagnosis(
            db,
            thread=thread,
            author=await db.get(User, invite.doctor_user_id),
            text=invite.diagnosis_text,
            template=template,
            status=DiagnosisStatus.VERIFIED,
        )

    # Documents the doctor attached move into the newly created thread.
    if invite.document_ids:
        await db.execute(
            sa.update(Document)
            .where(Document.id.in_([uuid.UUID(d) for d in invite.document_ids]))
            .values(care_thread_id=thread.id)
        )

    if not patient.full_name:
        patient.full_name = invite.full_name

    invite.status = InviteStatus.REDEEMED
    invite.redeemed_at = datetime.now(UTC)
    invite.redeemed_by_user_id = patient.id
    invite.care_thread_id = thread.id
    await db.flush()
    return thread


async def connect_to_doctor(
    db: AsyncSession, *, patient: User, doctor_user_id: uuid.UUID
) -> CareThread:
    """Create the isolated container for one patient-doctor pair."""
    existing = await db.scalar(
        sa.select(CareThread).where(
            CareThread.patient_user_id == patient.id,
            CareThread.doctor_user_id == doctor_user_id,
        )
    )
    if existing is not None:
        if existing.archived_at is not None:
            existing.archived_at = None
            existing.status = "active"
            await db.flush()
            return existing
        raise ConflictError("already connected to this doctor", code="already_connected")

    profile = await db.scalar(
        sa.select(DoctorProfile).where(DoctorProfile.user_id == doctor_user_id)
    )
    if profile is None:
        raise NotFoundError("doctor not found", code="doctor_not_found")

    now = datetime.now(UTC)
    thread = CareThread(
        patient_user_id=patient.id,
        doctor_user_id=doctor_user_id,
        kind=CareThreadKind.DOCTOR,
        title=profile.full_name,
        connected_at=now,
        last_activity_at=now,
    )
    db.add(thread)
    await db.flush()

    doctor = await db.get(User, doctor_user_id)
    if doctor is not None:
        from app.services.notifications import queue_notification

        await queue_notification(
            db,
            user=doctor,
            type=NotificationType.PATIENT_ADDED,
            title_key="push.patient_added.title",
            body_key="push.patient_added.body",
            params={"patient_name": patient.full_name or "Yangi bemor"},
            data={"screen": "patient", "care_thread_id": str(thread.id)},
            dedupe_key=f"patient-added:{thread.id}",
        )
    log.info("care.thread_created", thread_id=str(thread.id))
    return thread


async def share_personal_thread(
    db: AsyncSession, *, patient: User, source_thread_id: uuid.UUID, target_thread_id: uuid.UUID
) -> int:
    """Copy the personal container into a doctor thread after consent (spec 2.2).

    Records are *copied*, not moved: the patient keeps their own history, and the
    doctor receives everything as unverified until they review it.
    """
    source = await db.get(CareThread, source_thread_id)
    target = await db.get(CareThread, target_thread_id)
    if source is None or target is None:
        raise NotFoundError("care thread not found", code="thread_not_found")
    if source.patient_user_id != patient.id or target.patient_user_id != patient.id:
        raise ForbiddenError("not your care thread", code="not_yours")
    if not source.is_personal:
        raise ValidationError("source must be the personal container", code="invalid_source")
    if target.is_personal:
        raise ValidationError("target must be a doctor thread", code="invalid_target")

    copied = 0

    diagnoses = (
        await db.scalars(
            sa.select(Diagnosis).where(
                Diagnosis.care_thread_id == source.id, Diagnosis.is_active.is_(True)
            )
        )
    ).all()
    for diagnosis in diagnoses:
        db.add(
            Diagnosis(
                care_thread_id=target.id,
                text=diagnosis.text,
                template_id=diagnosis.template_id,
                # Patient-supplied history is unverified until the doctor confirms.
                status=DiagnosisStatus.UNVERIFIED,
                created_by_user_id=patient.id,
                notes=diagnosis.notes,
            )
        )
        copied += 1

    medications = (
        await db.scalars(
            sa.select(Medication).where(
                Medication.care_thread_id == source.id, Medication.is_active.is_(True)
            )
        )
    ).all()
    for medication in medications:
        new_medication = Medication(
            care_thread_id=target.id,
            name=medication.name,
            dose=medication.dose,
            instructions=medication.instructions,
            times=list(medication.times or []),
            weekdays=list(medication.weekdays or []),
            starts_on=medication.starts_on,
            ends_on=medication.ends_on,
            created_by_user_id=patient.id,
        )
        db.add(new_medication)
        await db.flush()
        from app.services.medications import materialize_doses

        await materialize_doses(db, new_medication)
        copied += 1

    series_list = (
        await db.scalars(sa.select(MetricSeries).where(MetricSeries.care_thread_id == source.id))
    ).all()
    for series in series_list:
        target_series = await db.scalar(
            sa.select(MetricSeries).where(
                MetricSeries.care_thread_id == target.id, MetricSeries.key == series.key
            )
        )
        if target_series is None:
            target_series = MetricSeries(
                care_thread_id=target.id,
                key=series.key,
                label=series.label,
                unit=series.unit,
                value_type=series.value_type,
                target_min=series.target_min,
                target_max=series.target_max,
                critical_min=series.critical_min,
                critical_max=series.critical_max,
                decimals=series.decimals,
                chart_type=series.chart_type,
                sort_order=series.sort_order,
            )
            db.add(target_series)
            await db.flush()

        readings = (
            await db.scalars(sa.select(MetricReading).where(MetricReading.series_id == series.id))
        ).all()
        for reading in readings:
            db.add(
                MetricReading(
                    series_id=target_series.id,
                    care_thread_id=target.id,
                    value=reading.value,
                    value_secondary=reading.value_secondary,
                    recorded_at=reading.recorded_at,
                    source=reading.source,
                    note=reading.note,
                    recorded_by_user_id=reading.recorded_by_user_id,
                )
            )
            copied += 1

    await db.flush()
    log.info("care.personal_shared", target=str(target.id), records=copied)
    return copied


# ------------------------------------------------------------------- diagnoses
async def create_diagnosis(
    db: AsyncSession,
    *,
    thread: CareThread,
    author: User | None,
    text: str,
    template: DiagnosisTemplate | None = None,
    status: DiagnosisStatus = DiagnosisStatus.UNVERIFIED,
    notes: str | None = None,
    auto_match: bool = True,
) -> Diagnosis:
    if template is None and auto_match:
        match = await match_template(db, text)
        template = match.template

    diagnosis = Diagnosis(
        care_thread_id=thread.id,
        text=text.strip(),
        template_id=template.id if template else None,
        status=status,
        created_by_user_id=author.id if author else None,
        notes=notes,
        verified_by_user_id=author.id if (author and status == DiagnosisStatus.VERIFIED) else None,
        verified_at=datetime.now(UTC) if status == DiagnosisStatus.VERIFIED else None,
    )
    db.add(diagnosis)
    await db.flush()

    # Charts are created from the template as soon as the diagnosis is verified.
    if template is not None and status == DiagnosisStatus.VERIFIED:
        await apply_template_to_thread(db, thread.id, template)

    thread.last_activity_at = datetime.now(UTC)
    await db.flush()

    if status == DiagnosisStatus.UNVERIFIED and thread.doctor_user_id:
        doctor = await db.get(User, thread.doctor_user_id)
        patient = await db.get(User, thread.patient_user_id)
        if doctor is not None:
            from app.services.notifications import queue_notification

            await queue_notification(
                db,
                user=doctor,
                type=NotificationType.DIAGNOSIS_PENDING,
                title_key="push.diagnosis_pending.title",
                body_key="push.diagnosis_pending.body",
                params={"patient_name": (patient.full_name if patient else None) or "Bemor"},
                data={
                    "screen": "patient",
                    "care_thread_id": str(thread.id),
                    "diagnosis_id": str(diagnosis.id),
                },
                dedupe_key=f"diagnosis-pending:{diagnosis.id}",
            )
    return diagnosis


async def verify_diagnosis(
    db: AsyncSession, diagnosis: Diagnosis, doctor: User, *, text: str | None = None
) -> Diagnosis:
    if text:
        diagnosis.text = text.strip()
    diagnosis.status = DiagnosisStatus.VERIFIED
    diagnosis.verified_by_user_id = doctor.id
    diagnosis.verified_at = datetime.now(UTC)
    await db.flush()

    if diagnosis.template_id:
        template = await db.get(DiagnosisTemplate, diagnosis.template_id)
        if template is not None:
            await apply_template_to_thread(db, diagnosis.care_thread_id, template)
    return diagnosis


def assert_patient_may_edit(diagnosis: Diagnosis) -> None:
    """Spec 2.3: a verified diagnosis is off-limits to the patient."""
    if diagnosis.status == DiagnosisStatus.VERIFIED:
        raise ForbiddenError(
            "a verified diagnosis can only be changed by the doctor; "
            "submit a change request instead",
            code="diagnosis_verified_readonly",
        )


async def create_change_request(
    db: AsyncSession,
    *,
    diagnosis: Diagnosis,
    patient: User,
    comment: str,
    proposed_text: str | None,
) -> DiagnosisChangeRequest:
    pending = await db.scalar(
        sa.select(DiagnosisChangeRequest.id).where(
            DiagnosisChangeRequest.diagnosis_id == diagnosis.id,
            DiagnosisChangeRequest.status == ChangeRequestStatus.PENDING,
        )
    )
    if pending:
        raise ConflictError("a change request is already pending", code="change_request_pending")

    request = DiagnosisChangeRequest(
        diagnosis_id=diagnosis.id,
        requested_by_user_id=patient.id,
        comment=comment.strip(),
        proposed_text=(proposed_text or "").strip() or None,
    )
    db.add(request)
    await db.flush()

    thread = await db.get(CareThread, diagnosis.care_thread_id)
    if thread is not None and thread.doctor_user_id:
        doctor = await db.get(User, thread.doctor_user_id)
        if doctor is not None:
            from app.services.notifications import queue_notification

            await queue_notification(
                db,
                user=doctor,
                type=NotificationType.DIAGNOSIS_CHANGE_REQUEST,
                title_key="push.diagnosis_change_request.title",
                body_key="push.diagnosis_change_request.body",
                params={"patient_name": patient.full_name or "Bemor"},
                data={
                    "screen": "patient",
                    "care_thread_id": str(thread.id),
                    "diagnosis_id": str(diagnosis.id),
                },
                dedupe_key=f"diagnosis-change:{request.id}",
            )
    return request


async def resolve_change_request(
    db: AsyncSession,
    *,
    request: DiagnosisChangeRequest,
    doctor: User,
    accept: bool,
    resolution_note: str | None,
    final_text: str | None,
) -> DiagnosisChangeRequest:
    diagnosis = await db.get(Diagnosis, request.diagnosis_id)
    if diagnosis is None:
        raise NotFoundError("diagnosis not found", code="diagnosis_not_found")

    request.status = ChangeRequestStatus.ACCEPTED if accept else ChangeRequestStatus.REJECTED
    request.resolved_by_user_id = doctor.id
    request.resolved_at = datetime.now(UTC)
    request.resolution_note = (resolution_note or "").strip() or None

    if accept:
        new_text = final_text or request.proposed_text
        await verify_diagnosis(db, diagnosis, doctor, text=new_text)
    await db.flush()
    return request


# ---------------------------------------------------------------- risk scoring
async def compute_risk(db: AsyncSession, thread_id: uuid.UUID) -> tuple[str, list[str]]:
    """Traffic-light risk for the doctor's patient list (spec 4.2 tab 1).

    Amber and red are driven by two signals a doctor actually acts on: readings
    outside the configured range, and missed medication.
    """
    reasons: list[str] = []
    score = 0
    now = datetime.now(UTC)
    week_ago = now - timedelta(days=7)

    series_list = (
        await db.scalars(
            sa.select(MetricSeries).where(
                MetricSeries.care_thread_id == thread_id, MetricSeries.is_active.is_(True)
            )
        )
    ).all()
    for series in series_list:
        readings = (
            await db.scalars(
                sa.select(MetricReading)
                .where(
                    MetricReading.series_id == series.id,
                    MetricReading.recorded_at >= week_ago,
                )
                .order_by(MetricReading.recorded_at.desc())
                .limit(20)
            )
        ).all()
        if not readings:
            continue

        critical = sum(
            1
            for r in readings
            if (series.critical_max is not None and r.value > series.critical_max)
            or (series.critical_min is not None and r.value < series.critical_min)
        )
        out_of_range = sum(
            1
            for r in readings
            if (series.target_max is not None and r.value > series.target_max)
            or (series.target_min is not None and r.value < series.target_min)
        )
        if critical:
            score += 3
            reasons.append(f"{series.key}: {critical} critical reading(s)")
        elif out_of_range >= max(2, len(readings) // 2):
            score += 1
            reasons.append(f"{series.key}: {out_of_range} reading(s) out of range")

    due = await db.scalar(
        sa.select(sa.func.count())
        .select_from(MedicationDose)
        .where(
            MedicationDose.care_thread_id == thread_id,
            MedicationDose.scheduled_at >= week_ago,
            MedicationDose.scheduled_at <= now,
        )
    )
    if due:
        missed = await db.scalar(
            sa.select(sa.func.count())
            .select_from(MedicationDose)
            .where(
                MedicationDose.care_thread_id == thread_id,
                MedicationDose.scheduled_at >= week_ago,
                MedicationDose.scheduled_at <= now,
                MedicationDose.status == DoseStatus.MISSED,
            )
        )
        missed_ratio = (missed or 0) / due
        if missed_ratio >= 0.4:
            score += 3
            reasons.append(f"medication adherence {round((1 - missed_ratio) * 100)}%")
        elif missed_ratio >= 0.2:
            score += 1
            reasons.append(f"medication adherence {round((1 - missed_ratio) * 100)}%")

    # No check-in for a week is itself a signal worth surfacing.
    last_checkin = await db.scalar(
        sa.select(sa.func.max(CheckinSubmission.submitted_at)).where(
            CheckinSubmission.care_thread_id == thread_id
        )
    )
    if last_checkin is not None:
        last = last_checkin if last_checkin.tzinfo else last_checkin.replace(tzinfo=UTC)
        if (now - last).days >= 7:
            score += 1
            reasons.append("no check-in for over a week")

    level = "red" if score >= 3 else "amber" if score >= 1 else "green"
    return level, reasons
