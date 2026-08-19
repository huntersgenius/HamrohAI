"""Consultation lifecycle and money rules (spec 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import sqlalchemy as sa

from app.core.errors import ConflictError, ForbiddenError
from app.models.billing import Wallet, WalletTransaction
from app.models.consultation import Consultation
from app.models.enums import (
    ConsultationStatus,
    ConsultationTargeting,
    DiagnosisStatus,
    NotificationType,
)
from app.models.notification import Notification
from app.models.profile import DoctorProfile
from app.services import consultations as service
from app.services.billing import split_amount
from app.services.care import create_diagnosis
from tests.conftest import make_doctor, make_patient, make_thread


class TestPricing:
    async def test_doctor_custom_price_wins(self, db) -> None:
        doctor, _ = await make_doctor(db, "+998901200001", price=75_000)
        await db.commit()
        price, specialty, custom = await service.quote_price(
            db, specialty=None, doctor_user_id=doctor.id
        )
        assert price == 75_000
        assert custom is True
        assert specialty == "endocrinologist"

    async def test_recommended_price_used_for_matching(self, db) -> None:
        price, specialty, custom = await service.quote_price(
            db, specialty="cardiologist", doctor_user_id=None
        )
        assert price == 60_000
        assert custom is False

    async def test_unverified_doctor_cannot_be_booked(self, db) -> None:
        from app.core.errors import ValidationError

        doctor, _ = await make_doctor(db, "+998901200002", approved=False)
        await db.commit()
        with pytest.raises(ValidationError):
            await service.quote_price(db, specialty=None, doctor_user_id=doctor.id)


class TestSnapshot:
    async def test_snapshot_only_includes_the_chosen_thread(self, db) -> None:
        """Attaching thread A must not leak thread B's data (spec 2.2)."""
        patient = await make_patient(db, "+998901200010")
        doctor_a, _ = await make_doctor(db, "+998901200011", full_name="A")
        doctor_b, _ = await make_doctor(db, "+998901200012", full_name="B")
        thread_a = await make_thread(db, patient, doctor_a)
        thread_b = await make_thread(db, patient, doctor_b)

        await create_diagnosis(
            db,
            thread=thread_a,
            author=doctor_a,
            text="Gipertoniya",
            status=DiagnosisStatus.VERIFIED,
        )
        await create_diagnosis(
            db,
            thread=thread_b,
            author=doctor_b,
            text="Qandli diabet",
            status=DiagnosisStatus.VERIFIED,
        )
        await db.commit()

        snapshot = await service.build_snapshot(db, thread=thread_a, patient=patient, share=True)
        texts = [d["text"] for d in snapshot["diagnoses"]]
        assert texts == ["Gipertoniya"]
        assert "Qandli diabet" not in texts

    async def test_declining_to_share_yields_no_clinical_data(self, db) -> None:
        patient = await make_patient(db, "+998901200013")
        doctor, _ = await make_doctor(db, "+998901200014")
        thread = await make_thread(db, patient, doctor)
        await create_diagnosis(
            db,
            thread=thread,
            author=doctor,
            text="Gipertoniya",
            status=DiagnosisStatus.VERIFIED,
        )
        await db.commit()

        snapshot = await service.build_snapshot(db, thread=thread, patient=patient, share=False)
        assert snapshot["shared"] is False
        assert snapshot["diagnoses"] == []

    async def test_snapshot_is_frozen_at_submit_time(self, db) -> None:
        """A later edit must not change what the doctor was shown."""
        patient = await make_patient(db, "+998901200015")
        doctor, _ = await make_doctor(db, "+998901200016")
        thread = await make_thread(db, patient, doctor)
        diagnosis = await create_diagnosis(
            db,
            thread=thread,
            author=doctor,
            text="Original",
            status=DiagnosisStatus.VERIFIED,
        )
        await db.commit()

        consultation = await service.create_consultation(
            db,
            patient=patient,
            doctor_user_id=doctor.id,
            specialty=None,
            question="Savolim bor",
            thread=thread,
            share_clinical_data=True,
            attachment_ids=[],
        )
        await db.commit()

        diagnosis.text = "Changed afterwards"
        await db.commit()
        await db.refresh(consultation)

        assert consultation.snapshot["diagnoses"][0]["text"] == "Original"


class TestClaimExclusivity:
    async def test_only_one_doctor_can_claim(self, db) -> None:
        patient = await make_patient(db, "+998901200020")
        first, _ = await make_doctor(db, "+998901200021", specialty="cardiologist")
        second, _ = await make_doctor(db, "+998901200022", specialty="cardiologist")
        await db.commit()

        consultation = await service.create_consultation(
            db,
            patient=patient,
            doctor_user_id=None,
            specialty="cardiologist",
            question="Savol",
            thread=None,
            share_clinical_data=False,
            attachment_ids=[],
        )
        await db.commit()
        await service.activate_paid_consultation(db, consultation.id)
        await db.commit()

        await service.claim(db, consultation.id, first)
        await db.commit()

        # The second doctor loses the race and is told so, not silently ignored.
        with pytest.raises(ConflictError) as excinfo:
            await service.claim(db, consultation.id, second)
        assert excinfo.value.code == "already_claimed"

    async def test_direct_request_cannot_be_taken_by_someone_else(self, db) -> None:
        patient = await make_patient(db, "+998901200023")
        intended, _ = await make_doctor(db, "+998901200024")
        other, _ = await make_doctor(db, "+998901200025")
        await db.commit()

        consultation = await service.create_consultation(
            db,
            patient=patient,
            doctor_user_id=intended.id,
            specialty=None,
            question="Savol",
            thread=None,
            share_clinical_data=False,
            attachment_ids=[],
        )
        await db.commit()
        await service.activate_paid_consultation(db, consultation.id)
        await db.commit()

        with pytest.raises(ForbiddenError):
            await service.claim(db, consultation.id, other)

    async def test_specialty_mismatch_is_rejected(self, db) -> None:
        patient = await make_patient(db, "+998901200026")
        dentist, _ = await make_doctor(db, "+998901200027", specialty="dentist")
        await db.commit()

        consultation = await service.create_consultation(
            db,
            patient=patient,
            doctor_user_id=None,
            specialty="cardiologist",
            question="Savol",
            thread=None,
            share_clinical_data=False,
            attachment_ids=[],
        )
        await db.commit()
        await service.activate_paid_consultation(db, consultation.id)
        await db.commit()

        with pytest.raises(ForbiddenError):
            await service.claim(db, consultation.id, dentist)


class TestMoney:
    def test_split_is_exactly_80_20_and_loses_nothing(self) -> None:
        earning, fee = split_amount(50_000)
        assert earning == 40_000
        assert fee == 10_000
        assert earning + fee == 50_000

    @pytest.mark.parametrize("total", [1, 7, 33_333, 49_999, 123_457])
    def test_split_always_reconciles(self, total: int) -> None:
        earning, fee = split_amount(total)
        assert earning + fee == total
        assert earning >= 0 and fee >= 0

    async def test_answering_credits_the_doctor_wallet(self, db) -> None:
        patient = await make_patient(db, "+998901200030")
        doctor, _ = await make_doctor(db, "+998901200031", price=50_000)
        await db.commit()

        consultation = await _paid_consultation(db, patient, doctor)
        await service.answer(db, consultation.id, doctor, "Javob matni")
        await db.commit()

        wallet = await db.scalar(sa.select(Wallet).where(Wallet.user_id == doctor.id))
        assert wallet.balance_uzs == 40_000
        assert wallet.lifetime_earned_uzs == 40_000

        await db.refresh(consultation)
        assert consultation.doctor_earning_uzs == 40_000
        assert consultation.platform_fee_uzs == 10_000

    async def test_earning_is_credited_only_once(self, db) -> None:
        """The idempotency key must survive a retried credit."""
        from app.services.billing import credit_consultation_earning

        patient = await make_patient(db, "+998901200032")
        doctor, _ = await make_doctor(db, "+998901200033", price=50_000)
        await db.commit()

        consultation = await _paid_consultation(db, patient, doctor)
        await service.answer(db, consultation.id, doctor, "Javob")
        await db.commit()

        await credit_consultation_earning(db, consultation, doctor)
        await db.commit()

        wallet = await db.scalar(sa.select(Wallet).where(Wallet.user_id == doctor.id))
        assert wallet.balance_uzs == 40_000

        transactions = await db.scalar(
            sa.select(sa.func.count())
            .select_from(WalletTransaction)
            .where(WalletTransaction.wallet_id == wallet.id)
        )
        assert transactions == 1

    async def test_payout_below_minimum_is_refused(self, db) -> None:
        from app.core.errors import ValidationError
        from app.services.billing import get_or_create_wallet, request_payout

        doctor, _ = await make_doctor(db, "+998901200034")
        wallet = await get_or_create_wallet(db, doctor.id)
        wallet.balance_uzs = 100_000
        await db.commit()

        with pytest.raises(ValidationError) as excinfo:
            await request_payout(
                db,
                user=doctor,
                amount_uzs=10_000,
                card_number="8600123412341234",
                card_holder="A B",
            )
        assert excinfo.value.code == "payout_below_minimum"

    async def test_payout_holds_the_balance_and_stores_only_last4(self, db) -> None:
        from app.services.billing import get_or_create_wallet, request_payout

        doctor, _ = await make_doctor(db, "+998901200035")
        wallet = await get_or_create_wallet(db, doctor.id)
        wallet.balance_uzs = 100_000
        await db.commit()

        payout = await request_payout(
            db,
            user=doctor,
            amount_uzs=60_000,
            card_number="8600 1234 1234 5678",
            card_holder="BOBUR RASULOV",
        )
        await db.commit()
        await db.refresh(wallet)

        assert wallet.balance_uzs == 40_000
        assert payout.card_last4 == "5678"
        # The full PAN must never be persisted anywhere.
        assert "8600123412345678" not in (payout.destination_ref or "")


class TestSlaRefund:
    async def test_unanswered_after_24h_is_refunded(self, db) -> None:
        patient = await make_patient(db, "+998901200040")
        doctor, _ = await make_doctor(db, "+998901200041")
        await db.commit()

        consultation = await _paid_consultation(db, patient, doctor, claim=False)
        # Push the deadline into the past.
        consultation.sla_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

        refunded = await service.expire_unanswered(db)
        await db.commit()
        assert refunded == 1

        await db.refresh(consultation)
        assert consultation.status == ConsultationStatus.REFUNDED
        assert consultation.refunded_at is not None

    async def test_refund_notifies_the_patient(self, db) -> None:
        patient = await make_patient(db, "+998901200042")
        doctor, _ = await make_doctor(db, "+998901200043")
        await db.commit()

        consultation = await _paid_consultation(db, patient, doctor, claim=False)
        consultation.sla_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

        await service.expire_unanswered(db)
        await db.commit()

        notification = await db.scalar(
            sa.select(Notification).where(
                Notification.user_id == patient.id,
                Notification.type == NotificationType.CONSULTATION_REFUNDED,
            )
        )
        assert notification is not None

    async def test_answered_consultation_is_never_refunded(self, db) -> None:
        patient = await make_patient(db, "+998901200044")
        doctor, _ = await make_doctor(db, "+998901200045")
        await db.commit()

        consultation = await _paid_consultation(db, patient, doctor)
        await service.answer(db, consultation.id, doctor, "Javob")
        consultation.sla_expires_at = datetime.now(UTC) - timedelta(hours=2)
        await db.commit()

        refunded = await service.expire_unanswered(db)
        await db.commit()
        assert refunded == 0

        await db.refresh(consultation)
        assert consultation.status == ConsultationStatus.ANSWERED


    async def test_refund_moves_the_payment_row_too(self, db) -> None:
        """A refunded consultation must not leave a PAID payment behind.

        Otherwise reconciliation against Click/Payme shows money received with
        no matching refund record.
        """
        from app.models.enums import PaymentProvider, PaymentPurpose, PaymentStatus
        from app.services.billing import create_payment

        patient = await make_patient(db, "+998901200046")
        doctor, _ = await make_doctor(db, "+998901200047")
        await db.commit()

        consultation = await _paid_consultation(db, patient, doctor, claim=False)
        payment = await create_payment(
            db,
            user=patient,
            provider=PaymentProvider.CLICK,
            purpose=PaymentPurpose.CONSULTATION,
            amount_uzs=consultation.price_uzs,
            consultation_id=consultation.id,
        )
        payment.status = PaymentStatus.PAID
        consultation.sla_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        await db.commit()

        await service.expire_unanswered(db)
        await db.commit()

        await db.refresh(payment)
        assert payment.status == PaymentStatus.REFUNDED
        assert payment.refunded_at is not None
        # Flagged for the operator: the provider-side reversal is manual.
        assert payment.provider_payload["refund_pending_operator"] is True

    async def test_refund_is_idempotent_across_payments(self, db) -> None:
        from app.models.enums import PaymentProvider, PaymentPurpose, PaymentStatus
        from app.services.billing import create_payment

        patient = await make_patient(db, "+998901200048")
        doctor, _ = await make_doctor(db, "+998901200049")
        await db.commit()

        consultation = await _paid_consultation(db, patient, doctor, claim=False)
        payment = await create_payment(
            db,
            user=patient,
            provider=PaymentProvider.PAYME,
            purpose=PaymentPurpose.CONSULTATION,
            amount_uzs=consultation.price_uzs,
            consultation_id=consultation.id,
        )
        payment.status = PaymentStatus.PAID
        await db.commit()

        await service.mark_refunded(db, consultation.id)
        await db.commit()
        first = payment.refunded_at

        await service.mark_refunded(db, consultation.id)
        await db.commit()
        await db.refresh(payment)
        assert payment.refunded_at == first


class TestRating:
    async def test_rating_updates_the_doctor_average(self, db) -> None:
        patient = await make_patient(db, "+998901200050")
        doctor, profile = await make_doctor(db, "+998901200051")
        await db.commit()

        consultation = await _paid_consultation(db, patient, doctor)
        await service.answer(db, consultation.id, doctor, "Javob")
        await db.commit()

        await service.rate(db, consultation.id, patient, 5, "Rahmat")
        await db.commit()

        refreshed = await db.scalar(
            sa.select(DoctorProfile).where(DoctorProfile.user_id == doctor.id)
        )
        assert refreshed.rating_count == 1
        assert refreshed.rating_average == 5.0

    async def test_only_the_patient_may_rate(self, db) -> None:
        patient = await make_patient(db, "+998901200052")
        doctor, _ = await make_doctor(db, "+998901200053")
        stranger = await make_patient(db, "+998901200054")
        await db.commit()

        consultation = await _paid_consultation(db, patient, doctor)
        await service.answer(db, consultation.id, doctor, "Javob")
        await db.commit()

        with pytest.raises(ForbiddenError):
            await service.rate(db, consultation.id, stranger, 5, None)


class TestAnonymity:
    async def test_matched_request_is_anonymous_until_claimed(self, db) -> None:
        patient = await make_patient(db, "+998901200060", full_name="Bobur")
        await db.commit()

        consultation = Consultation(
            patient_user_id=patient.id,
            targeting=ConsultationTargeting.MATCHED,
            specialty="cardiologist",
            question="Savol",
            price_uzs=60_000,
            status=ConsultationStatus.OPEN,
        )
        db.add(consultation)
        await db.flush()

        label = service.display_name_for_doctor(consultation, "Bobur")
        assert "Anonim" in label
        assert "Bobur" not in label

        consultation.status = ConsultationStatus.CLAIMED
        assert service.display_name_for_doctor(consultation, "Bobur") == "Bobur"

    async def test_direct_request_shows_the_name(self, db) -> None:
        patient = await make_patient(db, "+998901200061", full_name="Bobur")
        await db.commit()
        consultation = Consultation(
            patient_user_id=patient.id,
            targeting=ConsultationTargeting.DIRECT,
            specialty="cardiologist",
            question="Savol",
            price_uzs=60_000,
            status=ConsultationStatus.OPEN,
        )
        assert service.display_name_for_doctor(consultation, "Bobur") == "Bobur"


async def _paid_consultation(db, patient, doctor, *, claim: bool = True) -> Consultation:
    consultation = await service.create_consultation(
        db,
        patient=patient,
        doctor_user_id=doctor.id,
        specialty=None,
        question="Savolim bor",
        thread=None,
        share_clinical_data=False,
        attachment_ids=[],
    )
    await db.commit()
    await service.activate_paid_consultation(db, consultation.id)
    await db.commit()
    if claim:
        await service.claim(db, consultation.id, doctor)
        await db.commit()
    await db.refresh(consultation)
    return consultation
