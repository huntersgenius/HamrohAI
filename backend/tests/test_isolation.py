"""Care-thread isolation (spec 2.2) — the platform's core structural rule.

A patient may be connected to several doctors. Each connection is a completely
separate container: one doctor's diagnoses, medications, readings and AI history
must never be reachable from another doctor's thread.

These tests attack that boundary from every direction available to a caller.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from app.core.errors import ForbiddenError, NotFoundError
from app.models.care import CareThread, Diagnosis, MetricReading, MetricSeries
from app.models.enums import DiagnosisStatus
from app.services.access import (
    get_or_create_personal_thread,
    resolve_thread,
    visible_thread_filter,
)
from app.services.care import create_diagnosis
from tests.conftest import auth_headers, make_doctor, make_patient, make_thread


@pytest.fixture
async def two_doctor_setup(db):
    """One patient, two doctors, one thread each, with data in both."""
    patient = await make_patient(db, "+998901000010")
    cardiologist, _ = await make_doctor(
        db, "+998901000011", specialty="cardiologist", full_name="Dr Cardio"
    )
    endocrinologist, _ = await make_doctor(
        db, "+998901000012", specialty="endocrinologist", full_name="Dr Endo"
    )

    cardio_thread = await make_thread(db, patient, cardiologist)
    endo_thread = await make_thread(db, patient, endocrinologist)

    await create_diagnosis(
        db,
        thread=cardio_thread,
        author=cardiologist,
        text="Arterial gipertoniya",
        status=DiagnosisStatus.VERIFIED,
    )
    await create_diagnosis(
        db,
        thread=endo_thread,
        author=endocrinologist,
        text="Qandli diabet, 2-tur",
        status=DiagnosisStatus.VERIFIED,
    )
    await db.commit()
    return {
        "patient": patient,
        "cardiologist": cardiologist,
        "endocrinologist": endocrinologist,
        "cardio_thread": cardio_thread,
        "endo_thread": endo_thread,
    }


class TestThreadResolution:
    async def test_doctor_cannot_resolve_another_doctors_thread(self, db, two_doctor_setup) -> None:
        setup = two_doctor_setup
        # Not Forbidden but NotFound: an outsider must not even learn the id exists.
        with pytest.raises(NotFoundError):
            await resolve_thread(db, setup["endo_thread"].id, setup["cardiologist"])

    async def test_doctor_resolves_their_own_thread(self, db, two_doctor_setup) -> None:
        setup = two_doctor_setup
        access = await resolve_thread(db, setup["cardio_thread"].id, setup["cardiologist"])
        assert access.is_doctor
        assert access.thread_id == setup["cardio_thread"].id

    async def test_patient_resolves_both_of_their_threads(self, db, two_doctor_setup) -> None:
        setup = two_doctor_setup
        for key in ("cardio_thread", "endo_thread"):
            access = await resolve_thread(db, setup[key].id, setup["patient"])
            assert access.is_patient

    async def test_unrelated_user_sees_nothing(self, db, two_doctor_setup) -> None:
        other = await make_patient(db, "+998901000013")
        await db.commit()
        with pytest.raises(NotFoundError):
            await resolve_thread(db, two_doctor_setup["cardio_thread"].id, other)

    async def test_doctor_guard_rejects_the_patient(self, db, two_doctor_setup) -> None:
        setup = two_doctor_setup
        access = await resolve_thread(db, setup["cardio_thread"].id, setup["patient"])
        with pytest.raises(ForbiddenError):
            access.require_doctor()


class TestListFiltering:
    async def test_doctor_list_shows_only_their_threads(self, db, two_doctor_setup) -> None:
        setup = two_doctor_setup
        threads = (
            await db.scalars(
                sa.select(CareThread).where(visible_thread_filter(setup["cardiologist"]))
            )
        ).all()
        ids = {t.id for t in threads}
        assert ids == {setup["cardio_thread"].id}
        assert setup["endo_thread"].id not in ids

    async def test_patient_list_shows_every_thread_of_theirs(self, db, two_doctor_setup) -> None:
        setup = two_doctor_setup
        threads = (
            await db.scalars(sa.select(CareThread).where(visible_thread_filter(setup["patient"])))
        ).all()
        assert {t.id for t in threads} == {
            setup["cardio_thread"].id,
            setup["endo_thread"].id,
        }


class TestApiIsolation:
    async def test_cross_thread_read_is_404_over_http(self, client, db, two_doctor_setup) -> None:
        setup = two_doctor_setup
        headers = await auth_headers(db, setup["cardiologist"])

        response = await client.get(
            f"/api/v1/threads/{setup['endo_thread'].id}/diagnoses", headers=headers
        )
        assert response.status_code == 404
        assert response.json()["code"] == "thread_not_found"

    async def test_diagnoses_never_bleed_between_threads(
        self, client, db, two_doctor_setup
    ) -> None:
        setup = two_doctor_setup
        headers = await auth_headers(db, setup["cardiologist"])

        response = await client.get(
            f"/api/v1/threads/{setup['cardio_thread'].id}/diagnoses", headers=headers
        )
        assert response.status_code == 200
        texts = [d["text"] for d in response.json()]
        assert texts == ["Arterial gipertoniya"]
        assert "Qandli diabet, 2-tur" not in texts

    async def test_doctor_thread_list_excludes_other_doctors(
        self, client, db, two_doctor_setup
    ) -> None:
        setup = two_doctor_setup
        headers = await auth_headers(db, setup["endocrinologist"])

        response = await client.get("/api/v1/threads", headers=headers)
        assert response.status_code == 200
        ids = {item["id"] for item in response.json()}
        assert ids == {str(setup["endo_thread"].id)}

    async def test_id_from_another_thread_cannot_be_used_as_a_child_record(
        self, client, db, two_doctor_setup
    ) -> None:
        """A valid diagnosis id + your own thread id must still be rejected."""
        setup = two_doctor_setup
        foreign_diagnosis = await db.scalar(
            sa.select(Diagnosis).where(Diagnosis.care_thread_id == setup["endo_thread"].id)
        )
        headers = await auth_headers(db, setup["cardiologist"])

        response = await client.post(
            f"/api/v1/threads/{setup['cardio_thread'].id}/diagnoses/{foreign_diagnosis.id}/verify",
            headers=headers,
        )
        assert response.status_code == 404
        assert response.json()["code"] == "diagnosis_not_found"

    async def test_readings_are_scoped_to_their_thread(self, client, db, two_doctor_setup) -> None:
        setup = two_doctor_setup
        series = MetricSeries(
            care_thread_id=setup["endo_thread"].id,
            key="blood_glucose",
            label={"uz": "Qand"},
            unit="mmol/L",
        )
        db.add(series)
        await db.flush()
        db.add(
            MetricReading(
                series_id=series.id,
                care_thread_id=setup["endo_thread"].id,
                value=7.5,
                recorded_at=sa.func.now(),
            )
        )
        await db.commit()

        headers = await auth_headers(db, setup["cardiologist"])
        # The cardiologist owns a thread, but not this series.
        response = await client.get(
            f"/api/v1/threads/{setup['cardio_thread'].id}/series/{series.id}/trend",
            headers=headers,
        )
        assert response.status_code == 404


class TestPersonalContainer:
    async def test_personal_thread_is_created_once(self, db) -> None:
        patient = await make_patient(db, "+998901000020")
        first = await get_or_create_personal_thread(db, patient)
        await db.commit()
        second = await get_or_create_personal_thread(db, patient)
        await db.commit()
        assert first.id == second.id
        assert first.is_personal

    async def test_database_rejects_a_second_personal_thread(self, db) -> None:
        """The partial unique index is the real guarantee, not the code path."""
        from sqlalchemy.exc import IntegrityError

        from app.models.enums import CareThreadKind

        patient = await make_patient(db, "+998901000021")
        await get_or_create_personal_thread(db, patient)
        await db.commit()

        db.add(
            CareThread(
                patient_user_id=patient.id,
                doctor_user_id=None,
                kind=CareThreadKind.PERSONAL,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()

    async def test_doctor_cannot_reach_the_personal_container(self, db) -> None:
        patient = await make_patient(db, "+998901000022")
        doctor, _ = await make_doctor(db, "+998901000023")
        await make_thread(db, patient, doctor)
        personal = await get_or_create_personal_thread(db, patient)
        await db.commit()

        with pytest.raises(NotFoundError):
            await resolve_thread(db, personal.id, doctor)

    async def test_sharing_copies_data_and_marks_it_unverified(self, db) -> None:
        """Consent moves history across, but the doctor still has to confirm it."""
        from app.services.care import share_personal_thread

        patient = await make_patient(db, "+998901000024")
        doctor, _ = await make_doctor(db, "+998901000025")
        personal = await get_or_create_personal_thread(db, patient)
        thread = await make_thread(db, patient, doctor)

        await create_diagnosis(
            db,
            thread=personal,
            author=patient,
            text="Qandli diabet",
            status=DiagnosisStatus.UNVERIFIED,
        )
        await db.commit()

        copied = await share_personal_thread(
            db, patient=patient, source_thread_id=personal.id, target_thread_id=thread.id
        )
        await db.commit()
        assert copied >= 1

        moved = (
            await db.scalars(sa.select(Diagnosis).where(Diagnosis.care_thread_id == thread.id))
        ).all()
        assert len(moved) == 1
        assert moved[0].status == DiagnosisStatus.UNVERIFIED

        # The patient keeps their own copy.
        kept = (
            await db.scalars(sa.select(Diagnosis).where(Diagnosis.care_thread_id == personal.id))
        ).all()
        assert len(kept) == 1

class TestEngineIsPostgres:
    """The isolation guarantees below are only meaningful on PostgreSQL.

    The personal-container rule is enforced by a *partial* unique index, which
    SQLite does not support. If someone repoints TEST_DATABASE_URL at SQLite the
    suite would still go green while silently testing nothing, so the engine is
    asserted explicitly.
    """

    async def test_tests_run_against_postgresql(self, db) -> None:
        version = await db.scalar(sa.text("SELECT version()"))
        assert "PostgreSQL" in version, version
        assert db.bind.dialect.name == "postgresql"

    async def test_the_partial_unique_index_actually_exists(self, db) -> None:
        indexdef = await db.scalar(
            sa.text(
                "SELECT indexdef FROM pg_indexes "
                "WHERE indexname = 'uq_care_thread_personal'"
            )
        )
        assert indexdef is not None, "the personal-container index is missing"
        assert "WHERE (doctor_user_id IS NULL)" in indexdef, indexdef
