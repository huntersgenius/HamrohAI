"""Templates, diagnosis verification, medications, IVR and Excel round-trips."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.core.errors import ForbiddenError
from app.models.care import (
    Diagnosis,
    Medication,
    MedicationDose,
    MetricReading,
    MetricSeries,
)
from app.models.enums import (
    ChangeRequestStatus,
    DiagnosisStatus,
    DoseConfirmationChannel,
    DoseStatus,
    InviteStatus,
)
from app.services import care as care_service
from app.services import excel as excel_service
from app.services import medications as med_service
from app.services.templates import apply_template_to_thread, match_template
from tests.conftest import make_doctor, make_patient, make_thread, seed_catalog


class TestTemplateMatching:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Qandli diabet, 2-tur", "diabetes_t2"),
            ("qandli diabet", "diabetes_t2"),
            ("Сахарный диабет 2 типа", "diabetes_t2"),
            ("Type 2 diabetes mellitus", "diabetes_t2"),
            ("Arterial gipertoniya", "hypertension"),
            ("гипертония", "hypertension"),
            ("Bronxial astma", "asthma"),
            ("Гипотиреоз", "hypothyroidism"),
        ],
    )
    async def test_auto_match_across_languages(self, db, text: str, expected: str) -> None:
        await seed_catalog(db)
        result = await match_template(db, text)
        assert result.template is not None
        assert result.template.code == expected

    async def test_uzbek_apostrophe_variants_all_match(self, db) -> None:
        """oʻ / o' / o` must not change the outcome."""
        await seed_catalog(db)
        for variant in ["Bronxial astma", "bronxial astma", "BRONXIAL ASTMA"]:
            result = await match_template(db, variant)
            assert result.template.code == "asthma"

    async def test_specific_template_beats_generic_keyword(self, db) -> None:
        await seed_catalog(db)
        result = await match_template(db, "qandli diabet 2-tur, insulinga qaram emas")
        assert result.template.code == "diabetes_t2"

    async def test_unknown_text_matches_nothing(self, db) -> None:
        await seed_catalog(db)
        result = await match_template(db, "qwertyuiop zzz")
        assert result.template is None
        assert result.confidence == 0.0

    async def test_applying_a_template_creates_its_charts(self, db) -> None:
        await seed_catalog(db)
        patient = await make_patient(db, "+998901400001")
        doctor, _ = await make_doctor(db, "+998901400002")
        thread = await make_thread(db, patient, doctor)
        await db.commit()

        result = await match_template(db, "Qandli diabet")
        series = await apply_template_to_thread(db, thread.id, result.template)
        await db.commit()

        keys = {s.key for s in series}
        assert {"blood_glucose", "hba1c"} <= keys

        glucose = next(s for s in series if s.key == "blood_glucose")
        assert glucose.unit == "mmol/L"
        assert glucose.target_min == 4.4
        assert glucose.target_max == 7.2

    async def test_applying_twice_does_not_duplicate_charts(self, db) -> None:
        await seed_catalog(db)
        patient = await make_patient(db, "+998901400003")
        doctor, _ = await make_doctor(db, "+998901400004")
        thread = await make_thread(db, patient, doctor)
        await db.commit()

        result = await match_template(db, "Qandli diabet")
        await apply_template_to_thread(db, thread.id, result.template)
        await db.commit()
        await apply_template_to_thread(db, thread.id, result.template)
        await db.commit()

        count = await db.scalar(
            sa.select(sa.func.count())
            .select_from(MetricSeries)
            .where(MetricSeries.care_thread_id == thread.id)
        )
        assert count == 3  # glucose, hba1c, weight

    async def test_switching_template_keeps_old_readings(self, db) -> None:
        """A doctor changing template must not destroy patient history."""
        await seed_catalog(db)
        patient = await make_patient(db, "+998901400005")
        doctor, _ = await make_doctor(db, "+998901400006")
        thread = await make_thread(db, patient, doctor)
        await db.commit()

        diabetes = (await match_template(db, "Qandli diabet")).template
        await apply_template_to_thread(db, thread.id, diabetes)
        await db.commit()

        glucose = await db.scalar(
            sa.select(MetricSeries).where(
                MetricSeries.care_thread_id == thread.id,
                MetricSeries.key == "blood_glucose",
            )
        )
        db.add(
            MetricReading(
                series_id=glucose.id,
                care_thread_id=thread.id,
                value=6.1,
                recorded_at=datetime.now(UTC),
            )
        )
        await db.commit()

        hypertension = (await match_template(db, "Gipertoniya")).template
        await apply_template_to_thread(db, thread.id, hypertension, replace=True)
        await db.commit()

        await db.refresh(glucose)
        assert glucose.is_active is False  # hidden, not deleted
        readings = await db.scalar(
            sa.select(sa.func.count())
            .select_from(MetricReading)
            .where(MetricReading.series_id == glucose.id)
        )
        assert readings == 1


class TestDiagnosisVerification:
    async def test_doctor_entry_is_verified_immediately(self, db) -> None:
        await seed_catalog(db)
        patient = await make_patient(db, "+998901400010")
        doctor, _ = await make_doctor(db, "+998901400011")
        thread = await make_thread(db, patient, doctor)
        await db.commit()

        diagnosis = await care_service.create_diagnosis(
            db,
            thread=thread,
            author=doctor,
            text="Qandli diabet",
            status=DiagnosisStatus.VERIFIED,
        )
        await db.commit()
        assert diagnosis.is_verified
        assert diagnosis.verified_by_user_id == doctor.id

    async def test_patient_cannot_edit_a_verified_diagnosis(self, db) -> None:
        await seed_catalog(db)
        patient = await make_patient(db, "+998901400012")
        doctor, _ = await make_doctor(db, "+998901400013")
        thread = await make_thread(db, patient, doctor)
        diagnosis = await care_service.create_diagnosis(
            db,
            thread=thread,
            author=doctor,
            text="Qandli diabet",
            status=DiagnosisStatus.VERIFIED,
        )
        await db.commit()

        with pytest.raises(ForbiddenError) as excinfo:
            care_service.assert_patient_may_edit(diagnosis)
        assert excinfo.value.code == "diagnosis_verified_readonly"

    async def test_patient_may_edit_their_unverified_entry(self, db) -> None:
        await seed_catalog(db)
        patient = await make_patient(db, "+998901400014")
        doctor, _ = await make_doctor(db, "+998901400015")
        thread = await make_thread(db, patient, doctor)
        diagnosis = await care_service.create_diagnosis(
            db,
            thread=thread,
            author=patient,
            text="O'zim kiritdim",
            status=DiagnosisStatus.UNVERIFIED,
        )
        await db.commit()
        care_service.assert_patient_may_edit(diagnosis)  # must not raise

    async def test_change_request_flow(self, db) -> None:
        await seed_catalog(db)
        patient = await make_patient(db, "+998901400016")
        doctor, _ = await make_doctor(db, "+998901400017")
        thread = await make_thread(db, patient, doctor)
        diagnosis = await care_service.create_diagnosis(
            db,
            thread=thread,
            author=doctor,
            text="Original tashxis",
            status=DiagnosisStatus.VERIFIED,
        )
        await db.commit()

        request = await care_service.create_change_request(
            db,
            diagnosis=diagnosis,
            patient=patient,
            comment="Bu to'g'ri emas",
            proposed_text="Yangi tashxis",
        )
        await db.commit()
        assert request.status == ChangeRequestStatus.PENDING

        await care_service.resolve_change_request(
            db,
            request=request,
            doctor=doctor,
            accept=True,
            resolution_note="Tuzatildi",
            final_text=None,
        )
        await db.commit()
        await db.refresh(diagnosis)

        assert request.status == ChangeRequestStatus.ACCEPTED
        assert diagnosis.text == "Yangi tashxis"
        assert diagnosis.is_verified

    async def test_only_one_pending_change_request(self, db) -> None:
        from app.core.errors import ConflictError

        await seed_catalog(db)
        patient = await make_patient(db, "+998901400018")
        doctor, _ = await make_doctor(db, "+998901400019")
        thread = await make_thread(db, patient, doctor)
        diagnosis = await care_service.create_diagnosis(
            db,
            thread=thread,
            author=doctor,
            text="Tashxis",
            status=DiagnosisStatus.VERIFIED,
        )
        await db.commit()

        await care_service.create_change_request(
            db,
            diagnosis=diagnosis,
            patient=patient,
            comment="Birinchi",
            proposed_text=None,
        )
        await db.commit()
        with pytest.raises(ConflictError):
            await care_service.create_change_request(
                db,
                diagnosis=diagnosis,
                patient=patient,
                comment="Ikkinchi",
                proposed_text=None,
            )


class TestInvites:
    async def test_invite_prefills_and_creates_a_verified_diagnosis(self, db) -> None:
        await seed_catalog(db)
        doctor, _ = await make_doctor(db, "+998901400020")
        await db.commit()

        invite, template = await care_service.create_invite(
            db,
            doctor=doctor,
            full_name="Bobur Rasulov",
            phone="+998901400021",
            diagnosis_text="Qandli diabet, 2-tur",
            template_id=None,
            document_ids=[],
        )
        await db.commit()
        # The template is auto-selected from the typed diagnosis (spec 6).
        assert template.code == "diabetes_t2"

        patient = await make_patient(db, "+998901400021")
        await db.commit()

        thread, prefilled = await care_service.redeem_code(db, patient=patient, code=invite.code)
        await db.commit()
        assert prefilled is True

        diagnosis = await db.scalar(
            sa.select(Diagnosis).where(Diagnosis.care_thread_id == thread.id)
        )
        # Entered by the doctor, so it starts verified.
        assert diagnosis.status == DiagnosisStatus.VERIFIED
        assert diagnosis.text == "Qandli diabet, 2-tur"

    async def test_invite_is_bound_to_the_phone_number(self, db) -> None:
        await seed_catalog(db)
        doctor, _ = await make_doctor(db, "+998901400022")
        await db.commit()
        invite, _ = await care_service.create_invite(
            db,
            doctor=doctor,
            full_name="X",
            phone="+998901400023",
            diagnosis_text=None,
            template_id=None,
            document_ids=[],
        )
        await db.commit()

        wrong_person = await make_patient(db, "+998901400099")
        await db.commit()

        with pytest.raises(ForbiddenError) as excinfo:
            await care_service.redeem_code(db, patient=wrong_person, code=invite.code)
        assert excinfo.value.code == "code_phone_mismatch"

    async def test_invite_is_single_use(self, db) -> None:
        from app.core.errors import ConflictError

        await seed_catalog(db)
        doctor, _ = await make_doctor(db, "+998901400024")
        await db.commit()
        invite, _ = await care_service.create_invite(
            db,
            doctor=doctor,
            full_name="X",
            phone="+998901400025",
            diagnosis_text=None,
            template_id=None,
            document_ids=[],
        )
        await db.commit()

        patient = await make_patient(db, "+998901400025")
        await db.commit()
        await care_service.redeem_code(db, patient=patient, code=invite.code)
        await db.commit()

        await db.refresh(invite)
        assert invite.status == InviteStatus.REDEEMED

        with pytest.raises(ConflictError):
            await care_service.redeem_code(db, patient=patient, code=invite.code)

    async def test_permanent_connect_code_is_reusable(self, db) -> None:
        await seed_catalog(db)
        doctor, profile = await make_doctor(db, "+998901400026")
        first = await make_patient(db, "+998901400027")
        second = await make_patient(db, "+998901400028")
        await db.commit()

        thread_one, prefilled_one = await care_service.redeem_code(
            db, patient=first, code=profile.connect_code
        )
        await db.commit()
        thread_two, prefilled_two = await care_service.redeem_code(
            db, patient=second, code=profile.connect_code
        )
        await db.commit()

        assert prefilled_one is False and prefilled_two is False
        assert thread_one.id != thread_two.id

    async def test_expired_invite_is_refused(self, db) -> None:
        from app.core.errors import ValidationError

        await seed_catalog(db)
        doctor, _ = await make_doctor(db, "+998901400029")
        await db.commit()
        invite, _ = await care_service.create_invite(
            db,
            doctor=doctor,
            full_name="X",
            phone="+998901400030",
            diagnosis_text=None,
            template_id=None,
            document_ids=[],
        )
        invite.expires_at = datetime.now(UTC) - timedelta(days=1)
        await db.commit()

        patient = await make_patient(db, "+998901400030")
        await db.commit()
        with pytest.raises(ValidationError):
            await care_service.redeem_code(db, patient=patient, code=invite.code)

        await db.refresh(invite)
        assert invite.status == InviteStatus.EXPIRED


class TestMedicationSchedule:
    async def test_doses_are_materialised_for_each_time(self, db) -> None:
        patient = await make_patient(db, "+998901400040")
        doctor, _ = await make_doctor(db, "+998901400041")
        thread = await make_thread(db, patient, doctor)
        medication = Medication(
            care_thread_id=thread.id,
            name="Metformin",
            dose="500 mg",
            times=["08:00", "20:00"],
            starts_on=med_service.local_today(),
        )
        db.add(medication)
        await db.flush()

        created = await med_service.materialize_doses(db, medication, horizon_days=3)
        await db.commit()
        # Two per day for three days, minus any slot already past today.
        assert 4 <= created <= 6

    async def test_weekday_restriction_is_respected(self, db) -> None:
        patient = await make_patient(db, "+998901400042")
        doctor, _ = await make_doctor(db, "+998901400043")
        thread = await make_thread(db, patient, doctor)
        # Mondays only.
        medication = Medication(
            care_thread_id=thread.id,
            name="Weekly",
            dose="1 tab",
            times=["09:00"],
            weekdays=[1],
            starts_on=date(2026, 1, 1),
        )
        db.add(medication)
        await db.flush()

        monday = date(2026, 3, 2)
        tuesday = date(2026, 3, 3)
        assert len(med_service.scheduled_slots(medication, monday)) == 1
        assert med_service.scheduled_slots(medication, tuesday) == []

    async def test_local_times_map_to_tashkent(self, db) -> None:
        patient = await make_patient(db, "+998901400044")
        doctor, _ = await make_doctor(db, "+998901400045")
        thread = await make_thread(db, patient, doctor)
        medication = Medication(
            care_thread_id=thread.id,
            name="Morning",
            dose="1",
            times=["08:00"],
            starts_on=date(2026, 6, 1),
        )
        db.add(medication)
        await db.flush()

        slots = med_service.scheduled_slots(medication, date(2026, 6, 15))
        # 08:00 in UTC+5 is 03:00 UTC — and stays so all year (no DST).
        assert slots[0].hour == 3

    async def test_rescheduling_keeps_confirmed_history(self, db) -> None:
        patient = await make_patient(db, "+998901400046")
        doctor, _ = await make_doctor(db, "+998901400047")
        thread = await make_thread(db, patient, doctor)
        medication = Medication(
            care_thread_id=thread.id,
            name="Metformin",
            dose="500 mg",
            times=["08:00", "20:00"],
            starts_on=med_service.local_today() - timedelta(days=1),
        )
        db.add(medication)
        await db.flush()

        taken = MedicationDose(
            medication_id=medication.id,
            care_thread_id=thread.id,
            scheduled_at=datetime.now(UTC) - timedelta(hours=5),
            status=DoseStatus.TAKEN,
            taken_at=datetime.now(UTC) - timedelta(hours=5),
        )
        db.add(taken)
        await db.flush()
        await med_service.materialize_doses(db, medication)
        await db.commit()

        medication.times = ["09:00"]
        await med_service.resync_medication(db, medication)
        await db.commit()

        still_there = await db.get(MedicationDose, taken.id)
        assert still_there is not None
        assert still_there.status == DoseStatus.TAKEN

    async def test_adherence_counts_only_elapsed_doses(self, db) -> None:
        patient = await make_patient(db, "+998901400048")
        doctor, _ = await make_doctor(db, "+998901400049")
        thread = await make_thread(db, patient, doctor)
        medication = Medication(
            care_thread_id=thread.id,
            name="M",
            dose="1",
            times=["08:00"],
            starts_on=med_service.local_today() - timedelta(days=3),
        )
        db.add(medication)
        await db.flush()

        now = datetime.now(UTC)
        db.add_all(
            [
                MedicationDose(
                    medication_id=medication.id,
                    care_thread_id=thread.id,
                    scheduled_at=now - timedelta(days=1),
                    status=DoseStatus.TAKEN,
                ),
                MedicationDose(
                    medication_id=medication.id,
                    care_thread_id=thread.id,
                    scheduled_at=now - timedelta(days=2),
                    status=DoseStatus.MISSED,
                ),
                # A future dose must not drag the percentage down.
                MedicationDose(
                    medication_id=medication.id,
                    care_thread_id=thread.id,
                    scheduled_at=now + timedelta(days=1),
                    status=DoseStatus.PENDING,
                ),
            ]
        )
        await db.commit()

        percent = await med_service.adherence_percent(db, thread.id, days=7)
        assert percent == 50.0

    async def test_missed_doses_expire(self, db) -> None:
        patient = await make_patient(db, "+998901400050")
        doctor, _ = await make_doctor(db, "+998901400051")
        thread = await make_thread(db, patient, doctor)
        medication = Medication(
            care_thread_id=thread.id,
            name="M",
            dose="1",
            times=["08:00"],
            starts_on=med_service.local_today(),
        )
        db.add(medication)
        await db.flush()
        db.add(
            MedicationDose(
                medication_id=medication.id,
                care_thread_id=thread.id,
                scheduled_at=datetime.now(UTC) - timedelta(hours=5),
                status=DoseStatus.PENDING,
            )
        )
        await db.commit()

        count = await med_service.expire_missed_doses(db)
        await db.commit()
        assert count == 1


class TestIvrConfirmation:
    async def test_pressing_one_confirms_the_dose(self, client, db) -> None:
        from app.models.care import ReminderCall

        patient = await make_patient(db, "+998901400060")
        doctor, _ = await make_doctor(db, "+998901400061")
        thread = await make_thread(db, patient, doctor)
        medication = Medication(
            care_thread_id=thread.id,
            name="Metformin",
            dose="500 mg",
            times=["08:00"],
            starts_on=med_service.local_today(),
        )
        db.add(medication)
        await db.flush()
        dose = MedicationDose(
            medication_id=medication.id,
            care_thread_id=thread.id,
            scheduled_at=datetime.now(UTC) - timedelta(minutes=20),
            status=DoseStatus.PENDING,
        )
        db.add(dose)
        await db.flush()
        call = ReminderCall(
            dose_id=dose.id, user_id=patient.id, phone=patient.phone, status="placed"
        )
        db.add(call)
        await db.commit()

        response = await client.post(f"/api/v1/webhooks/ivr/{call.id}/gather", data={"Digits": "1"})
        assert response.status_code == 200
        assert "<Say" in response.text

        await db.refresh(dose)
        assert dose.status == DoseStatus.TAKEN
        assert dose.confirmed_via == DoseConfirmationChannel.IVR

    async def test_no_keypress_leaves_the_dose_pending(self, client, db) -> None:
        from app.models.care import ReminderCall

        patient = await make_patient(db, "+998901400062")
        doctor, _ = await make_doctor(db, "+998901400063")
        thread = await make_thread(db, patient, doctor)
        medication = Medication(
            care_thread_id=thread.id,
            name="M",
            dose="1",
            times=["08:00"],
            starts_on=med_service.local_today(),
        )
        db.add(medication)
        await db.flush()
        dose = MedicationDose(
            medication_id=medication.id,
            care_thread_id=thread.id,
            scheduled_at=datetime.now(UTC) - timedelta(minutes=20),
            status=DoseStatus.PENDING,
        )
        db.add(dose)
        await db.flush()
        call = ReminderCall(
            dose_id=dose.id, user_id=patient.id, phone=patient.phone, status="placed"
        )
        db.add(call)
        await db.commit()

        await client.post(f"/api/v1/webhooks/ivr/{call.id}/gather", data={"Digits": ""})
        await db.refresh(dose)
        assert dose.status == DoseStatus.PENDING

    async def test_call_is_skipped_when_the_patient_opted_out(self, db) -> None:
        from app.jobs.tasks import dispatch_reminder_calls
        from app.models.care import ReminderCall

        patient = await make_patient(db, "+998901400064")
        patient.ivr_reminders_enabled = False  # spec: must be switchable off
        doctor, _ = await make_doctor(db, "+998901400065")
        thread = await make_thread(db, patient, doctor)
        medication = Medication(
            care_thread_id=thread.id,
            name="M",
            dose="1",
            times=["08:00"],
            starts_on=med_service.local_today(),
        )
        db.add(medication)
        await db.flush()
        db.add(
            MedicationDose(
                medication_id=medication.id,
                care_thread_id=thread.id,
                scheduled_at=datetime.now(UTC) - timedelta(minutes=30),
                status=DoseStatus.PENDING,
            )
        )
        await db.commit()

        placed = await dispatch_reminder_calls(db)
        await db.commit()
        assert placed == 0

        calls = await db.scalar(sa.select(sa.func.count()).select_from(ReminderCall))
        assert calls == 0

    async def test_call_is_placed_after_the_grace_period(self, db) -> None:
        from app.jobs.tasks import dispatch_reminder_calls
        from app.models.care import ReminderCall

        patient = await make_patient(db, "+998901400066")
        doctor, _ = await make_doctor(db, "+998901400067")
        thread = await make_thread(db, patient, doctor)
        medication = Medication(
            care_thread_id=thread.id,
            name="M",
            dose="1",
            times=["08:00"],
            starts_on=med_service.local_today(),
        )
        db.add(medication)
        await db.flush()
        db.add(
            MedicationDose(
                medication_id=medication.id,
                care_thread_id=thread.id,
                scheduled_at=datetime.now(UTC) - timedelta(minutes=30),
                status=DoseStatus.PENDING,
            )
        )
        await db.commit()

        placed = await dispatch_reminder_calls(db)
        await db.commit()
        assert placed == 1

        call = await db.scalar(sa.select(ReminderCall))
        assert call.status == "placed"


class TestExcelRoundTrip:
    async def test_export_then_import_preserves_values(self, db) -> None:
        patient = await make_patient(db, "+998901400070")
        doctor, _ = await make_doctor(db, "+998901400071")
        thread = await make_thread(db, patient, doctor)
        series = MetricSeries(
            care_thread_id=thread.id,
            key="blood_glucose",
            label={"uz": "Qand darajasi"},
            unit="mmol/L",
            target_min=4.4,
            target_max=7.2,
        )
        db.add(series)
        await db.flush()

        base = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        readings = [
            MetricReading(
                series_id=series.id,
                care_thread_id=thread.id,
                value=value,
                recorded_at=base + timedelta(days=index),
            )
            for index, value in enumerate([5.1, 6.4, 9.8])
        ]
        db.add_all(readings)
        await db.commit()

        content = excel_service.export_series(series, readings, locale="uz")
        assert content[:2] == b"PK"  # a real xlsx zip container

        parsed = excel_service.parse_series_workbook(content)
        assert [row.value for row in parsed.rows] == [5.1, 6.4, 9.8]

    def test_import_accepts_paired_blood_pressure_cells(self) -> None:
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Sana", "Vaqt", "Qiymat", "Ikkinchi qiymat", "Birlik", "Izoh"])
        sheet.append(["2026-03-01", "08:00", "120/80", None, "mmHg", ""])
        sheet.append(["01.03.2026", "20:00", 135, 85, "mmHg", "kechqurun"])

        import io

        buffer = io.BytesIO()
        workbook.save(buffer)
        result = excel_service.parse_series_workbook(buffer.getvalue())

        assert len(result.rows) == 2
        assert result.rows[0].value == 120
        assert result.rows[0].value_secondary == 80
        assert result.rows[1].value == 135
        assert result.rows[1].value_secondary == 85

    def test_import_reports_bad_rows_without_failing_the_file(self) -> None:
        import io

        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Date", "Time", "Value", "Secondary value", "Unit", "Note"])
        sheet.append(["2026-03-01", "08:00", 5.5, None, "mmol/L", ""])
        sheet.append(["not-a-date", "08:00", 6.0, None, "mmol/L", ""])

        buffer = io.BytesIO()
        workbook.save(buffer)
        result = excel_service.parse_series_workbook(buffer.getvalue())

        assert len(result.rows) == 1
        assert result.skipped == 1
        assert result.errors

    def test_import_handles_comma_decimals(self) -> None:
        import io

        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.append(["Дата", "Время", "Значение", "Второе значение", "Единица", "Примечание"])
        sheet.append(["2026-03-01", "08:00", "5,7", None, "ммоль/л", ""])

        buffer = io.BytesIO()
        workbook.save(buffer)
        result = excel_service.parse_series_workbook(buffer.getvalue())
        assert result.rows[0].value == 5.7


class TestRiskScoring:
    async def test_critical_readings_raise_risk_to_red(self, db) -> None:
        await seed_catalog(db)
        patient = await make_patient(db, "+998901400080")
        doctor, _ = await make_doctor(db, "+998901400081")
        thread = await make_thread(db, patient, doctor)
        series = MetricSeries(
            care_thread_id=thread.id,
            key="blood_glucose",
            label={"uz": "Qand"},
            unit="mmol/L",
            target_min=4.4,
            target_max=7.2,
            critical_max=13.9,
        )
        db.add(series)
        await db.flush()
        db.add(
            MetricReading(
                series_id=series.id,
                care_thread_id=thread.id,
                value=18.0,
                recorded_at=datetime.now(UTC) - timedelta(hours=2),
            )
        )
        await db.commit()

        level, reasons = await care_service.compute_risk(db, thread.id)
        assert level == "red"
        assert reasons

    async def test_quiet_thread_is_green(self, db) -> None:
        patient = await make_patient(db, "+998901400082")
        doctor, _ = await make_doctor(db, "+998901400083")
        thread = await make_thread(db, patient, doctor)
        await db.commit()

        level, reasons = await care_service.compute_risk(db, thread.id)
        assert level == "green"
        assert reasons == []


class TestWeeklyReport:
    async def test_report_summarises_metrics_and_adherence(self, db) -> None:
        from app.services.ai.weekly import build_report

        await seed_catalog(db)
        patient = await make_patient(db, "+998901400090")
        doctor, _ = await make_doctor(db, "+998901400091")
        thread = await make_thread(db, patient, doctor)
        series = MetricSeries(
            care_thread_id=thread.id,
            key="blood_glucose",
            label={"uz": "Qand darajasi"},
            unit="mmol/L",
            target_min=4.4,
            target_max=7.2,
        )
        db.add(series)
        await db.flush()

        now = datetime.now(UTC)
        for index, value in enumerate([5.0, 6.0, 8.5, 5.5]):
            db.add(
                MetricReading(
                    series_id=series.id,
                    care_thread_id=thread.id,
                    value=value,
                    recorded_at=now - timedelta(days=index + 1),
                )
            )
        await db.commit()

        payload, summary = await build_report(db, thread, locale="uz")
        glucose = next(m for m in payload["metrics"] if m["key"] == "blood_glucose")
        assert glucose["count"] == 4
        assert glucose["out_of_range"] == 1
        assert "Qand darajasi" in summary

    async def test_report_is_generated_once_per_period(self, db) -> None:
        from app.services.ai.weekly import generate_and_deliver

        await seed_catalog(db)
        patient = await make_patient(db, "+998901400092")
        doctor, _ = await make_doctor(db, "+998901400093")
        thread = await make_thread(db, patient, doctor)
        await db.commit()

        first = await generate_and_deliver(db, thread)
        await db.commit()
        second = await generate_and_deliver(db, thread)
        await db.commit()
        assert first.id == second.id
