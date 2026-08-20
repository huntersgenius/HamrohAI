"""Mock mode (Task 4): every external integration runs without real keys.

The Click/Payme merchant, Eskiz/Play Mobile and Twilio applications are not yet
approved, so no credentials exist. Mock mode has to be strong enough that the
whole product can be exercised end to end anyway, and honest enough that what it
proves still means something once the keys arrive.

Two properties are therefore asserted throughout this file:

1. **Nothing leaves the process.** ``httpx.AsyncClient`` is replaced with a class
   that fails the test if it is ever constructed.
2. **The real handlers still run.** The payment mock does not set
   ``status = PAID``; it synthesises the provider's own callback — with a real
   Click MD5 signature over the real field order, and the real Payme JSON-RPC
   method sequence — and feeds it to the production handler.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from app.core.config import Settings, settings
from app.models.billing import Payment, Wallet, WalletTransaction
from app.models.consultation import Consultation
from app.models.enums import (
    ConsultationStatus,
    PaymentProvider,
    PaymentPurpose,
    PaymentStatus,
)
from app.services import ivr as ivr_service
from app.services import sms as sms_service
from app.services.billing import build_checkout_url, create_payment
from app.services.mocks import mocked_integrations, outbox
from app.services.payments import click
from app.services.payments import mock as payment_mock
from tests.conftest import auth_headers, make_doctor, make_patient


@pytest.fixture(autouse=True)
def _empty_outbox():
    outbox.clear()
    yield
    outbox.clear()


@pytest.fixture
def no_network(monkeypatch):
    """Make any real outbound HTTP call an immediate, obvious test failure."""

    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError(
                "mock mode must not open an HTTP client to a provider"
            )

    monkeypatch.setattr("httpx.AsyncClient", ExplodingClient)
    return ExplodingClient


class TestModeReporting:
    async def test_every_integration_is_mocked_under_test(self) -> None:
        assert mocked_integrations() == {
            "sms": True,
            "ivr": True,
            "push": True,
            "payments": True,
            "ai": True,
        }

    async def test_health_reports_which_integrations_are_simulated(self, client) -> None:
        response = await client.get("/health")
        assert response.status_code == 200
        assert response.json()["mocked_integrations"]["payments"] is True

    async def test_mock_status_endpoint_names_the_env_vars(self, client) -> None:
        response = await client.get("/api/v1/mock/status")
        assert response.status_code == 200
        body = response.json()
        assert body["env_vars"]["payments"] == "PAYMENT_MODE=mock"
        assert body["mocked"]["sms"] is True

    def test_production_refuses_to_start_in_mock_mode(self) -> None:
        """The one mistake this configuration must never allow."""
        with pytest.raises(ValueError, match="PAYMENT_MODE=real"):
            Settings(
                ENV="production",
                SECRET_KEY="x" * 40,
                SMS_MODE="real",
                IVR_MODE="real",
                PUSH_MODE="real",
                AI_MODE="real",
                PAYMENT_MODE="mock",
            )

    def test_production_accepts_real_mode(self) -> None:
        produced = Settings(
            ENV="production",
            SECRET_KEY="x" * 40,
            SMS_MODE="real",
            IVR_MODE="real",
            PUSH_MODE="real",
            AI_MODE="real",
            PAYMENT_MODE="real",
        )
        assert produced.PAYMENT_MODE == "real"

    async def test_mock_routes_are_refused_when_env_is_production(self, monkeypatch) -> None:
        from app.api.v1 import mock as mock_api
        from app.core.errors import NotFoundError

        monkeypatch.setattr(settings, "ENV", "production")
        with pytest.raises(NotFoundError):
            mock_api._guard()


class TestSmsMock:
    async def test_otp_is_readable_from_the_outbox_and_nothing_is_sent(
        self, client, no_network
    ) -> None:
        """The full sign-in flow works with no SMS provider account."""
        response = await client.post("/api/v1/auth/phone/start", json={"phone": "+998901400001"})
        assert response.status_code == 200, response.text
        challenge_id = response.json()["challenge_id"]

        event = outbox.latest("sms")
        assert event is not None
        assert event.target == "+998901400001"
        # The code the patient would have read off their handset.
        code = "".join(ch for ch in event.summary if ch.isdigit())[-settings.OTP_LENGTH :]
        assert len(code) == settings.OTP_LENGTH

        verify = await client.post(
            "/api/v1/auth/phone/verify",
            json={
                "phone": "+998901400001",
                "challenge_id": challenge_id,
                "code": code,
            },
        )
        assert verify.status_code == 200, verify.text
        assert verify.json()["tokens"]["access_token"]

    async def test_the_provider_resolves_to_the_mock(self) -> None:
        sms_service.set_sms_provider(None)
        assert isinstance(sms_service.get_sms_provider(), sms_service.MockSmsProvider)


class TestIvrMock:
    @staticmethod
    async def _pending_call(db, phone: str):
        """A dose that is 20 minutes overdue, with its reminder call queued."""
        from datetime import UTC, datetime, timedelta

        from app.models.care import Medication, MedicationDose, ReminderCall
        from app.models.enums import DoseStatus
        from app.services import medications as med_service
        from app.services.access import get_or_create_personal_thread

        patient = await make_patient(db, phone)
        thread = await get_or_create_personal_thread(db, patient)
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
            dose_id=dose.id, user_id=patient.id, phone=patient.phone, status="scheduled"
        )
        db.add(call)
        await db.commit()
        return dose, call

    async def test_a_reminder_call_is_recorded_not_dialled(self, db, no_network) -> None:
        ivr_service.set_ivr_provider(None)
        _, call = await self._pending_call(db, "+998901400010")

        await ivr_service.place_reminder_call(call)
        await db.commit()

        assert call.status == "placed"
        assert call.provider_call_id.startswith("mock-call-")
        event = outbox.latest("ivr")
        assert event is not None
        assert event.payload["call_id"] == str(call.id)
        # The URL a tester POSTs `Digits=1` to, standing in for the keypad.
        assert f"/webhooks/ivr/{call.id}/gather" in event.payload["gather_url"]

    async def test_pressing_one_confirms_the_dose_without_twilio(
        self, client, db, no_network
    ) -> None:
        """The whole reminder chain, end to end, with no Twilio account."""
        from app.models.enums import DoseConfirmationChannel, DoseStatus

        ivr_service.set_ivr_provider(None)
        dose, call = await self._pending_call(db, "+998901400011")

        await ivr_service.place_reminder_call(call)
        await db.commit()

        response = await client.post(
            f"/api/v1/webhooks/ivr/{call.id}/gather", data={"Digits": "1"}
        )
        assert response.status_code == 200
        assert "<Response>" in response.text

        await db.refresh(dose)
        assert dose.status == DoseStatus.TAKEN
        assert dose.confirmed_via == DoseConfirmationChannel.IVR


class TestPaymentMockDrivesTheRealHandlers:
    """The point of the payment mock: production code runs, only the hop is gone."""

    async def test_click_mock_produces_a_signature_the_real_verifier_accepts(
        self, db, no_network
    ) -> None:
        patient = await make_patient(db, "+998901400020")
        payment = await create_payment(
            db,
            user=patient,
            provider=PaymentProvider.CLICK,
            purpose=PaymentPurpose.SUBSCRIPTION,
            amount_uzs=99_000,
            subscription_plan="monthly",
        )
        await db.commit()

        request = payment_mock._click_request(payment, action=0, trans_id="mock-t-1")
        assert click.verify_signature(request) is True

        # And the signature is real, not bypassed: change one byte and the
        # production verifier rejects it.
        import dataclasses

        tampered = dataclasses.replace(request, amount="1")
        assert click.verify_signature(tampered) is False

    async def test_click_mock_walks_prepare_then_complete(self, db, no_network) -> None:
        patient = await make_patient(db, "+998901400021")
        payment = await create_payment(
            db,
            user=patient,
            provider=PaymentProvider.CLICK,
            purpose=PaymentPurpose.SUBSCRIPTION,
            amount_uzs=99_000,
            subscription_plan="monthly",
        )
        await db.commit()

        result = await payment_mock.simulate_success(db, payment)
        await db.commit()
        await db.refresh(payment)

        assert result["provider"] == "click"
        assert result["stage"] == "complete"
        assert result["response"]["error"] == click.SUCCESS
        assert payment.status == PaymentStatus.PAID
        # PENDING was set by prepare, so the two-phase protocol really ran.
        assert payment.prepared_at is not None
        assert payment.paid_at is not None

    async def test_payme_mock_walks_create_then_perform(self, db, no_network) -> None:
        patient = await make_patient(db, "+998901400022")
        payment = await create_payment(
            db,
            user=patient,
            provider=PaymentProvider.PAYME,
            purpose=PaymentPurpose.SUBSCRIPTION,
            amount_uzs=99_000,
            subscription_plan="monthly",
        )
        await db.commit()

        result = await payment_mock.simulate_success(db, payment)
        await db.commit()
        await db.refresh(payment)

        assert result["provider"] == "payme"
        assert result["stage"] == "PerformTransaction"
        assert result["response"]["create"]["state"] == 1
        assert result["response"]["final"]["state"] == 2
        assert payment.status == PaymentStatus.PAID

    async def test_a_failed_payment_is_simulated_too(self, db, no_network) -> None:
        patient = await make_patient(db, "+998901400023")
        payment = await create_payment(
            db,
            user=patient,
            provider=PaymentProvider.CLICK,
            purpose=PaymentPurpose.SUBSCRIPTION,
            amount_uzs=99_000,
            subscription_plan="monthly",
        )
        await db.commit()

        await payment_mock.simulate_failure(db, payment)
        await db.commit()
        await db.refresh(payment)
        assert payment.status == PaymentStatus.CANCELLED


class TestConsultationFlowWithoutRealKeys:
    """Spec 7 end to end: pay, activate, answer, 80/20 — all in mock mode."""

    async def test_checkout_url_points_at_the_simulator(self, db) -> None:
        patient = await make_patient(db, "+998901400030")
        payment = await create_payment(
            db,
            user=patient,
            provider=PaymentProvider.CLICK,
            purpose=PaymentPurpose.CONSULTATION,
            amount_uzs=50_000,
        )
        await db.commit()
        url = build_checkout_url(payment)
        assert "my.click.uz" not in url
        assert f"/api/v1/mock/checkout/{payment.id}" in url

    async def test_the_stand_in_checkout_page_renders_and_warns(self, client, db) -> None:
        patient = await make_patient(db, "+998901400035")
        payment = await create_payment(
            db,
            user=patient,
            provider=PaymentProvider.CLICK,
            purpose=PaymentPurpose.CONSULTATION,
            amount_uzs=50_000,
        )
        await db.commit()

        page = await client.get(f"/api/v1/mock/checkout/{payment.id}")
        assert page.status_code == 200
        assert page.headers["content-type"].startswith("text/html")
        # Nobody may mistake this for a real payment page.
        assert "MOCK REJIM" in page.text
        assert "50,000" in page.text

    async def test_pay_a_consultation_and_credit_the_doctor(
        self, client, db, no_network
    ) -> None:
        doctor, _ = await make_doctor(db, "+998901400031", price=50_000)
        patient = await make_patient(db, "+998901400032")
        headers = await auth_headers(db, patient)

        created = await client.post(
            "/api/v1/consultations",
            headers=headers,
            json={
                "doctor_user_id": str(doctor.id),
                "question": "Qandim ertalab 9.1 chiqdi, nima qilay?",
                "share_clinical_data": False,
                "payment_provider": "click",
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        payment_id = body["payment_id"]
        assert f"/api/v1/mock/checkout/{payment_id}" in body["checkout_url"]

        # The consultation is invisible to doctors until money arrives.
        consultation_id = uuid.UUID(body["consultation"]["id"])
        consultation = await db.get(Consultation, consultation_id)
        assert consultation.status == ConsultationStatus.PENDING_PAYMENT

        # The gateway page's "pay" button.
        paid = await client.post(f"/api/v1/mock/payments/{payment_id}/confirm")
        assert paid.status_code == 200, paid.text
        assert paid.json()["payment_status"] == PaymentStatus.PAID.value

        await db.refresh(consultation)
        assert consultation.status == ConsultationStatus.OPEN
        assert consultation.sla_expires_at is not None

        # Doctor answers; the 80/20 split lands in the wallet.
        doctor_headers = await auth_headers(db, doctor)
        claimed = await client.post(
            f"/api/v1/consultations/{consultation_id}/claim", headers=doctor_headers
        )
        assert claimed.status_code == 200, claimed.text
        answered = await client.post(
            f"/api/v1/consultations/{consultation_id}/answer",
            headers=doctor_headers,
            json={"answer_text": "Ertalabki qand 9.1 — dozani o'zgartirmasdan avval ..."},
        )
        assert answered.status_code == 200, answered.text

        wallet = await db.scalar(sa.select(Wallet).where(Wallet.user_id == doctor.id))
        assert wallet is not None
        assert wallet.balance_uzs == 40_000  # 80% of 50 000
        credits = (
            await db.scalars(
                sa.select(WalletTransaction).where(WalletTransaction.wallet_id == wallet.id)
            )
        ).all()
        assert len(credits) == 1

    async def test_confirming_twice_does_not_pay_the_doctor_twice(
        self, client, db, no_network
    ) -> None:
        """Idempotency still holds when the callback is synthesised."""
        doctor, _ = await make_doctor(db, "+998901400033", price=50_000)
        patient = await make_patient(db, "+998901400034")
        headers = await auth_headers(db, patient)

        created = await client.post(
            "/api/v1/consultations",
            headers=headers,
            json={
                "doctor_user_id": str(doctor.id),
                "question": "Bosimim 150/95, davom etyapti.",
                "share_clinical_data": False,
                "payment_provider": "payme",
            },
        )
        payment_id = created.json()["payment_id"]

        first = await client.post(f"/api/v1/mock/payments/{payment_id}/confirm")
        second = await client.post(f"/api/v1/mock/payments/{payment_id}/confirm")
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["payment_status"] == PaymentStatus.PAID.value
        assert second.json()["stage"] == "already_paid"

        payments = (await db.scalars(sa.select(Payment))).all()
        assert len(payments) == 1

        # And the consultation opened exactly once.
        consultation = await db.scalar(sa.select(Consultation))
        assert consultation.status == ConsultationStatus.OPEN


class TestOutboxSurface:
    async def test_outbox_lists_what_was_simulated(self, client, no_network) -> None:
        await client.post("/api/v1/auth/phone/start", json={"phone": "+998901400040"})
        response = await client.get("/api/v1/mock/outbox?kind=sms")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] >= 1
        assert body["items"][0]["kind"] == "sms"

    async def test_outbox_can_be_cleared(self, client, no_network) -> None:
        await client.post("/api/v1/auth/phone/start", json={"phone": "+998901400041"})
        assert len(outbox) >= 1
        cleared = await client.delete("/api/v1/mock/outbox")
        assert cleared.status_code == 204
        assert len(outbox) == 0
