"""Operational CLI.

    python -m app.cli seed              load templates + protocols (idempotent)
    python -m app.cli demo              add demo doctor/patient (non-production)
    python -m app.cli approve-doctor +998901234567
    python -m app.cli payouts           list pending withdrawal requests
    python -m app.cli complete-payout <id>
    python -m app.cli run-job <name>

The doctor-approval and payout commands exist because the MVP ships without an
admin panel (spec 1, spec 7): both operations are performed by an operator
against the database, and these subcommands are the safe way to do it.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.protocols import PROTOCOLS
from app.catalog.templates import TEMPLATES
from app.core.config import settings
from app.core.db import dispose_engine, get_sessionmaker
from app.core.logging import configure_logging, get_logger
from app.core.phone import normalize_phone
from app.models.ai import Protocol, ProtocolChunk
from app.models.billing import PayoutRequest
from app.models.enums import DoctorVerificationStatus, PayoutStatus
from app.models.profile import DoctorProfile
from app.models.template import DiagnosisTemplate
from app.models.user import User

log = get_logger(__name__)


async def seed_templates(db: AsyncSession) -> int:
    """Insert or update the built-in diagnosis templates."""
    count = 0
    for spec in TEMPLATES:
        template = await db.scalar(
            sa.select(DiagnosisTemplate).where(DiagnosisTemplate.code == spec["code"])
        )
        if template is None:
            template = DiagnosisTemplate(code=spec["code"])
            db.add(template)
        template.name = spec["name"]
        template.description = spec.get("description", {})
        template.specialty = spec.get("specialty")
        template.icd10 = spec.get("icd10")
        template.keywords = spec.get("keywords", [])
        template.metrics = spec.get("metrics", [])
        template.checkin_questions = spec.get("checkin_questions", [])
        template.protocol_slugs = spec.get("protocol_slugs", [])
        template.sort_order = spec.get("sort_order", 100)
        template.is_active = True
        count += 1
    await db.flush()
    return count


async def seed_protocols(db: AsyncSession) -> int:
    """Insert or update the approved protocol corpus, one chunk per locale."""
    count = 0
    for spec in PROTOCOLS:
        protocol = await db.scalar(sa.select(Protocol).where(Protocol.slug == spec["slug"]))
        if protocol is None:
            protocol = Protocol(slug=spec["slug"])
            db.add(protocol)
            await db.flush()
        protocol.title = spec["title"]
        protocol.specialty = spec.get("specialty")
        protocol.source = spec.get("source")
        protocol.approved_at = protocol.approved_at or datetime.now(UTC)
        protocol.is_active = True

        # Chunks are replaced wholesale so an edited corpus never leaves stale
        # passages the retriever could still surface.
        await db.execute(sa.delete(ProtocolChunk).where(ProtocolChunk.protocol_id == protocol.id))
        for position, chunk in enumerate(spec.get("chunks", [])):
            for locale in ("uz", "ru", "en"):
                content = chunk.get(locale)
                if not content:
                    continue
                db.add(
                    ProtocolChunk(
                        protocol_id=protocol.id,
                        locale=locale,
                        heading=chunk.get("key"),
                        content=content,
                        tags=chunk.get("tags", []),
                        position=position,
                    )
                )
                count += 1
    await db.flush()
    return count


async def cmd_seed() -> None:
    async with get_sessionmaker()() as db:
        templates = await seed_templates(db)
        chunks = await seed_protocols(db)
        await db.commit()
    print(f"seeded {templates} templates and {chunks} protocol chunks")  # noqa: T201


async def cmd_approve_doctor(phone: str) -> None:
    """Manual licence approval — the MVP's verification step (spec 1)."""
    normalized = normalize_phone(phone)
    async with get_sessionmaker()() as db:
        user = await db.scalar(sa.select(User).where(User.phone == normalized))
        if user is None:
            print(f"no user with phone {normalized}", file=sys.stderr)  # noqa: T201
            raise SystemExit(1)
        profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
        if profile is None:
            print("this user has no doctor profile", file=sys.stderr)  # noqa: T201
            raise SystemExit(1)

        profile.verification_status = DoctorVerificationStatus.APPROVED
        profile.verified_at = datetime.now(UTC)
        await db.commit()
        print(  # noqa: T201
            f"approved {profile.full_name} ({normalized}); connect code: {profile.connect_code}"
        )


async def cmd_list_payouts() -> None:
    async with get_sessionmaker()() as db:
        rows = (
            await db.execute(
                sa.select(PayoutRequest, User)
                .join(User, User.id == PayoutRequest.user_id)
                .where(PayoutRequest.status == PayoutStatus.REQUESTED)
                .order_by(PayoutRequest.created_at)
            )
        ).all()
        if not rows:
            print("no pending payout requests")  # noqa: T201
            return
        for payout, user in rows:
            print(  # noqa: T201
                f"{payout.id}  {user.full_name or user.phone:<28} "
                f"{payout.amount_uzs:>10,} UZS  *{payout.card_last4}  "
                f"{payout.card_holder}"
            )


async def cmd_complete_payout(payout_id: str, note: str | None) -> None:
    """Mark a manually transferred payout as paid."""
    import uuid

    async with get_sessionmaker()() as db:
        payout = await db.get(PayoutRequest, uuid.UUID(payout_id))
        if payout is None:
            print("payout not found", file=sys.stderr)  # noqa: T201
            raise SystemExit(1)
        if payout.status != PayoutStatus.REQUESTED:
            print(f"payout is already {payout.status.value}", file=sys.stderr)  # noqa: T201
            raise SystemExit(1)

        payout.status = PayoutStatus.PAID
        payout.processed_at = datetime.now(UTC)
        payout.note = note
        await db.commit()
        print(f"payout {payout_id} marked as paid")  # noqa: T201


async def cmd_list_refunds() -> None:
    """Refunds awaiting a provider-side reversal.

    The SLA job returns the money in our ledger immediately; pushing the
    reversal to Click/Payme is a manual finance step in the MVP, so this is the
    operator's worklist.
    """
    from app.models.billing import Payment
    from app.models.consultation import Consultation
    from app.models.enums import PaymentStatus

    async with get_sessionmaker()() as db:
        rows = (
            await db.execute(
                sa.select(Payment, Consultation, User)
                .join(Consultation, Consultation.id == Payment.consultation_id)
                .join(User, User.id == Payment.user_id)
                .where(Payment.status == PaymentStatus.REFUNDED)
                .order_by(Payment.refunded_at)
            )
        ).all()
        pending = [
            (payment, consultation, user)
            for payment, consultation, user in rows
            if (payment.provider_payload or {}).get("refund_pending_operator")
        ]
        if not pending:
            print("no refunds awaiting a provider reversal")  # noqa: T201
            return
        for payment, consultation, user in pending:
            print(  # noqa: T201
                f"{payment.provider.value:<6} {payment.provider_transaction_id or '-':<24} "
                f"{payment.amount_uzs:>9,} UZS  {user.phone:<15} "
                f"consultation={consultation.id}"
            )


async def cmd_settle_refund(payment_id: str) -> None:
    """Mark a refund as pushed to the provider."""
    import uuid as _uuid

    from app.models.billing import Payment

    async with get_sessionmaker()() as db:
        payment = await db.get(Payment, _uuid.UUID(payment_id))
        if payment is None:
            print("payment not found", file=sys.stderr)  # noqa: T201
            raise SystemExit(1)
        payload = dict(payment.provider_payload or {})
        payload["refund_pending_operator"] = False
        payload["refund_settled_at"] = datetime.now(UTC).isoformat()
        payment.provider_payload = payload
        await db.commit()
        print(f"refund {payment_id} marked as settled")  # noqa: T201



async def cmd_run_job(name: str) -> None:
    from app.jobs.tasks import JOBS, run_job

    if name not in JOBS:
        print(f"unknown job. available: {', '.join(sorted(JOBS))}", file=sys.stderr)  # noqa: T201
        raise SystemExit(1)
    result = await run_job(name)
    print(f"{name}: {result}")  # noqa: T201


async def cmd_demo() -> None:
    """Create a demo doctor and patient for local testing."""
    if settings.is_production:
        print("refusing to create demo data in production", file=sys.stderr)  # noqa: T201
        raise SystemExit(1)

    from app.models.enums import UserRole
    from app.services.billing import start_trial
    from app.services.care import allocate_connect_code, create_diagnosis
    from app.services.medications import materialize_doses

    async with get_sessionmaker()() as db:
        doctor_phone = normalize_phone("+998901112233")
        patient_phone = normalize_phone("+998901112244")

        doctor = await db.scalar(sa.select(User).where(User.phone == doctor_phone))
        if doctor is None:
            doctor = User(
                phone=doctor_phone,
                phone_verified_at=datetime.now(UTC),
                role=UserRole.DOCTOR,
                full_name="Dr. Aziza Karimova",
                locale="uz",
            )
            db.add(doctor)
            await db.flush()

        profile = await db.scalar(
            sa.select(DoctorProfile).where(DoctorProfile.user_id == doctor.id)
        )
        if profile is None:
            profile = DoctorProfile(
                user_id=doctor.id,
                full_name="Aziza Karimova",
                age=41,
                specialty="endocrinologist",
                experience_years=14,
                verification_status=DoctorVerificationStatus.APPROVED,
                verified_at=datetime.now(UTC),
                connect_code=await allocate_connect_code(db),
                consultation_open=True,
                consultation_price_uzs=50_000,
            )
            db.add(profile)
            await db.flush()
            await start_trial(db, profile)

        patient = await db.scalar(sa.select(User).where(User.phone == patient_phone))
        if patient is None:
            patient = User(
                phone=patient_phone,
                phone_verified_at=datetime.now(UTC),
                role=UserRole.PATIENT,
                full_name="Bobur Rasulov",
                locale="uz",
            )
            db.add(patient)
            await db.flush()

        from app.models.profile import PatientProfile

        patient_profile = await db.scalar(
            sa.select(PatientProfile).where(PatientProfile.user_id == patient.id)
        )
        if patient_profile is None:
            db.add(PatientProfile(user_id=patient.id, full_name="Bobur Rasulov", gender="male"))

        from app.models.care import CareThread, Medication
        from app.models.enums import CareThreadKind, DiagnosisStatus

        thread = await db.scalar(
            sa.select(CareThread).where(
                CareThread.patient_user_id == patient.id,
                CareThread.doctor_user_id == doctor.id,
            )
        )
        if thread is None:
            thread = CareThread(
                patient_user_id=patient.id,
                doctor_user_id=doctor.id,
                kind=CareThreadKind.DOCTOR,
                title=profile.full_name,
                connected_at=datetime.now(UTC),
                last_activity_at=datetime.now(UTC),
            )
            db.add(thread)
            await db.flush()

            await create_diagnosis(
                db,
                thread=thread,
                author=doctor,
                text="Qandli diabet, 2-tur",
                status=DiagnosisStatus.VERIFIED,
            )
            medication = Medication(
                care_thread_id=thread.id,
                name="Metformin",
                dose="500 mg",
                times=["08:00", "20:00"],
                starts_on=datetime.now(UTC).date(),
                created_by_user_id=doctor.id,
            )
            db.add(medication)
            await db.flush()
            await materialize_doses(db, medication)

        await db.commit()
        print(  # noqa: T201
            "demo data ready\n"
            f"  doctor  {doctor_phone}  connect code: {profile.connect_code}\n"
            f"  patient {patient_phone}\n"
            "  sign in with OTP_DEBUG_RETURN_CODE=true to get codes from the API"
        )


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(prog="app.cli", description="Hamroh operations CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("seed", help="load diagnosis templates and protocols")
    sub.add_parser("demo", help="create demo doctor/patient (non-production only)")

    approve = sub.add_parser("approve-doctor", help="approve a doctor's licence")
    approve.add_argument("phone")

    sub.add_parser("payouts", help="list pending payout requests")
    sub.add_parser("refunds", help="list refunds awaiting a provider reversal")

    settle = sub.add_parser("settle-refund", help="mark a refund as pushed to the provider")
    settle.add_argument("payment_id")

    complete = sub.add_parser("complete-payout", help="mark a payout as transferred")
    complete.add_argument("payout_id")
    complete.add_argument("--note", default=None)

    job = sub.add_parser("run-job", help="run a scheduled job once")
    job.add_argument("name")

    args = parser.parse_args()

    async def _run() -> None:
        try:
            if args.command == "seed":
                await cmd_seed()
            elif args.command == "demo":
                await cmd_demo()
            elif args.command == "approve-doctor":
                await cmd_approve_doctor(args.phone)
            elif args.command == "payouts":
                await cmd_list_payouts()
            elif args.command == "refunds":
                await cmd_list_refunds()
            elif args.command == "settle-refund":
                await cmd_settle_refund(args.payment_id)
            elif args.command == "complete-payout":
                await cmd_complete_payout(args.payout_id, args.note)
            elif args.command == "run-job":
                await cmd_run_job(args.name)
        finally:
            await dispose_engine()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
