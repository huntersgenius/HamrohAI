"""Money: payment lifecycle, wallet ledger, payouts, subscriptions (spec 7).

Rules encoded here:

* the patient pays the full amount **before** the consultation is visible to any
  doctor;
* no answer within 24 hours -> automatic full refund;
* on answer, 80% credits the answering doctor's internal wallet and 20% is the
  platform's;
* the wallet is an internal ledger, not real money movement — payouts are
  settled manually in the MVP;
* doctors need an active subscription to manage patients.

Every credit carries an idempotency key so a retried webhook can never pay a
doctor twice.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import ConflictError, ForbiddenError, ValidationError
from app.core.i18n import format_money
from app.core.logging import get_logger
from app.models.billing import Payment, PayoutRequest, Wallet, WalletTransaction
from app.models.consultation import Consultation
from app.models.enums import (
    ConsultationStatus,
    NotificationType,
    PaymentProvider,
    PaymentPurpose,
    PaymentStatus,
    PayoutStatus,
    SubscriptionPlan,
    SubscriptionStatus,
    WalletTxnType,
)
from app.models.profile import DoctorProfile, DoctorSubscription
from app.models.user import User

log = get_logger(__name__)


def split_amount(total_uzs: int) -> tuple[int, int]:
    """Return ``(doctor_earning, platform_fee)``.

    The platform fee is rounded so that the two parts always sum back to the
    exact total — never leave a stray sum unaccounted for in a ledger.
    """
    platform_fee = round(total_uzs * settings.PLATFORM_FEE_PERCENT / 100)
    return total_uzs - platform_fee, platform_fee


# ------------------------------------------------------------------- payments
async def create_payment(
    db: AsyncSession,
    *,
    user: User,
    provider: PaymentProvider,
    purpose: PaymentPurpose,
    amount_uzs: int,
    consultation_id: uuid.UUID | None = None,
    subscription_plan: str | None = None,
) -> Payment:
    if amount_uzs <= 0:
        raise ValidationError("amount must be positive", code="invalid_amount")
    payment = Payment(
        user_id=user.id,
        provider=provider,
        purpose=purpose,
        status=PaymentStatus.CREATED,
        amount_uzs=amount_uzs,
        amount_minor=amount_uzs * 100,  # tiyin
        consultation_id=consultation_id,
        subscription_plan=subscription_plan,
    )
    db.add(payment)
    await db.flush()
    return payment


def build_checkout_url(payment: Payment) -> str:
    from app.services.mocks import payments_are_mocked
    from app.services.payments import click, payme

    if payments_are_mocked():
        # No merchant account exists yet: send the client to the in-process
        # simulator instead of a gateway that would reject the request.
        from app.services.payments import mock

        return mock.checkout_url(payment)

    if payment.provider == PaymentProvider.CLICK:
        return click.checkout_url(payment)
    return payme.checkout_url(payment)


async def on_payment_succeeded(db: AsyncSession, payment: Payment) -> None:
    """Provider confirmed the money. Activate whatever was bought."""
    if payment.purpose == PaymentPurpose.CONSULTATION and payment.consultation_id:
        from app.services.consultations import activate_paid_consultation

        await activate_paid_consultation(db, payment.consultation_id)
    elif payment.purpose == PaymentPurpose.SUBSCRIPTION:
        await activate_subscription(db, payment)
    log.info("billing.payment_succeeded", payment_id=str(payment.id))


async def on_payment_cancelled(db: AsyncSession, payment: Payment) -> None:
    if payment.purpose == PaymentPurpose.CONSULTATION and payment.consultation_id:
        consultation = await db.get(Consultation, payment.consultation_id)
        # Only an unpaid consultation is cancelled; a paid one that a provider
        # later cancels is handled as a refund instead.
        if consultation is not None and consultation.status in (
            ConsultationStatus.DRAFT,
            ConsultationStatus.PENDING_PAYMENT,
        ):
            consultation.status = ConsultationStatus.CANCELLED
            await db.flush()


async def on_payment_refunded(db: AsyncSession, payment: Payment) -> None:
    if payment.purpose == PaymentPurpose.CONSULTATION and payment.consultation_id:
        from app.services.consultations import mark_refunded

        await mark_refunded(db, payment.consultation_id, reason="provider_refund")


# --------------------------------------------------------------------- wallet
async def get_or_create_wallet(db: AsyncSession, user_id: uuid.UUID) -> Wallet:
    wallet = await db.scalar(sa.select(Wallet).where(Wallet.user_id == user_id))
    if wallet is None:
        wallet = Wallet(user_id=user_id, balance_uzs=0)
        db.add(wallet)
        await db.flush()
    return wallet


async def credit_wallet(
    db: AsyncSession,
    *,
    user: User,
    amount_uzs: int,
    type: WalletTxnType,
    description: str | None = None,
    consultation_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    notify: bool = True,
) -> WalletTransaction | None:
    """Add to a doctor's balance. Returns ``None`` if already applied."""
    if amount_uzs <= 0:
        raise ValidationError("credit must be positive", code="invalid_amount")

    if idempotency_key:
        existing = await db.scalar(
            sa.select(WalletTransaction).where(WalletTransaction.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return None

    wallet = await get_or_create_wallet(db, user.id)
    wallet.balance_uzs += amount_uzs
    wallet.lifetime_earned_uzs += amount_uzs

    transaction = WalletTransaction(
        wallet_id=wallet.id,
        type=type,
        amount_uzs=amount_uzs,
        balance_after_uzs=wallet.balance_uzs,
        description=description,
        consultation_id=consultation_id,
        idempotency_key=idempotency_key,
    )
    db.add(transaction)
    await db.flush()

    if notify:
        from app.services.notifications import queue_notification

        await queue_notification(
            db,
            user=user,
            type=NotificationType.WALLET_UPDATED,
            title_key="push.wallet_updated.title",
            body_key="push.wallet_updated.body",
            params={
                "amount": format_money(amount_uzs, user.locale),
                "balance": format_money(wallet.balance_uzs, user.locale),
            },
            data={"screen": "wallet"},
            dedupe_key=f"wallet:{transaction.id}",
        )
    return transaction


async def debit_wallet(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    amount_uzs: int,
    type: WalletTxnType,
    description: str | None = None,
    payout_request_id: uuid.UUID | None = None,
) -> WalletTransaction:
    wallet = await get_or_create_wallet(db, user_id)
    if wallet.balance_uzs < amount_uzs:
        raise ValidationError("insufficient balance", code="insufficient_balance")

    wallet.balance_uzs -= amount_uzs
    transaction = WalletTransaction(
        wallet_id=wallet.id,
        type=type,
        amount_uzs=-amount_uzs,
        balance_after_uzs=wallet.balance_uzs,
        description=description,
        payout_request_id=payout_request_id,
    )
    db.add(transaction)
    await db.flush()
    return transaction


async def credit_consultation_earning(
    db: AsyncSession, consultation: Consultation, doctor: User
) -> None:
    """Pay the doctor their 80% share for an answered consultation."""
    earning, fee = split_amount(consultation.price_uzs)
    consultation.doctor_earning_uzs = earning
    consultation.platform_fee_uzs = fee
    await credit_wallet(
        db,
        user=doctor,
        amount_uzs=earning,
        type=WalletTxnType.CONSULTATION_EARNING,
        description="Konsultatsiya uchun to'lov",
        consultation_id=consultation.id,
        # One credit per consultation, however many times a job retries.
        idempotency_key=f"consultation:{consultation.id}",
    )


# -------------------------------------------------------------------- payouts
async def request_payout(
    db: AsyncSession,
    *,
    user: User,
    amount_uzs: int,
    card_number: str,
    card_holder: str,
) -> PayoutRequest:
    """Create a withdrawal request (settled manually in the MVP)."""
    wallet = await get_or_create_wallet(db, user.id)
    if amount_uzs < settings.WALLET_MIN_PAYOUT_UZS:
        raise ValidationError(
            "amount below the minimum payout",
            code="payout_below_minimum",
            details={"min_uzs": settings.WALLET_MIN_PAYOUT_UZS},
        )
    if wallet.balance_uzs < amount_uzs:
        raise ValidationError("insufficient balance", code="insufficient_balance")

    pending = await db.scalar(
        sa.select(sa.func.count())
        .select_from(PayoutRequest)
        .where(
            PayoutRequest.user_id == user.id,
            PayoutRequest.status.in_([PayoutStatus.REQUESTED, PayoutStatus.PROCESSING]),
        )
    )
    if pending:
        raise ConflictError("a payout request is already pending", code="payout_pending")

    payout = PayoutRequest(
        user_id=user.id,
        amount_uzs=amount_uzs,
        status=PayoutStatus.REQUESTED,
        # Only the last four digits are kept; the full PAN is never stored.
        card_last4=card_number[-4:],
        card_holder=card_holder,
    )
    db.add(payout)
    await db.flush()

    # The balance is held immediately so it cannot be requested twice.
    await debit_wallet(
        db,
        user_id=user.id,
        amount_uzs=amount_uzs,
        type=WalletTxnType.PAYOUT,
        description=f"Pul yechish so'rovi (*{payout.card_last4})",
        payout_request_id=payout.id,
    )
    wallet.lifetime_paid_out_uzs += amount_uzs
    await db.flush()
    log.info("billing.payout_requested", user_id=str(user.id), amount=amount_uzs)
    return payout


# -------------------------------------------------------------- subscriptions
def _period_for(plan: SubscriptionPlan) -> timedelta:
    return timedelta(days=365 if plan == SubscriptionPlan.YEARLY else 30)


def subscription_price(plan: SubscriptionPlan) -> int:
    return (
        settings.DOCTOR_SUBSCRIPTION_YEARLY_UZS
        if plan == SubscriptionPlan.YEARLY
        else settings.DOCTOR_SUBSCRIPTION_MONTHLY_UZS
    )


async def start_trial(db: AsyncSession, profile: DoctorProfile) -> DoctorSubscription:
    subscription = DoctorSubscription(
        doctor_profile_id=profile.id,
        plan=SubscriptionPlan.MONTHLY,
        status=SubscriptionStatus.TRIAL,
        current_period_end=datetime.now(UTC)
        + timedelta(days=settings.DOCTOR_SUBSCRIPTION_TRIAL_DAYS),
    )
    db.add(subscription)
    await db.flush()
    return subscription


async def activate_subscription(db: AsyncSession, payment: Payment) -> None:
    profile = await db.scalar(
        sa.select(DoctorProfile).where(DoctorProfile.user_id == payment.user_id)
    )
    if profile is None:
        log.warning("billing.subscription_no_profile", payment_id=str(payment.id))
        return

    plan = SubscriptionPlan(payment.subscription_plan or SubscriptionPlan.MONTHLY.value)
    subscription = await db.scalar(
        sa.select(DoctorSubscription).where(DoctorSubscription.doctor_profile_id == profile.id)
    )
    now = datetime.now(UTC)
    if subscription is None:
        subscription = DoctorSubscription(
            doctor_profile_id=profile.id, plan=plan, current_period_end=now
        )
        db.add(subscription)

    # Renewing early extends the existing period instead of truncating it.
    current_end = subscription.current_period_end
    if current_end and current_end.tzinfo is None:
        current_end = current_end.replace(tzinfo=UTC)
    base = current_end if current_end and current_end > now else now

    subscription.plan = plan
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.current_period_end = base + _period_for(plan)
    subscription.cancelled_at = None
    await db.flush()
    log.info("billing.subscription_activated", user_id=str(payment.user_id), plan=plan.value)


def subscription_is_active(subscription: DoctorSubscription | None) -> bool:
    if subscription is None:
        return False
    if subscription.status not in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL):
        return False
    end = subscription.current_period_end
    if end is None:
        return False
    if end.tzinfo is None:
        end = end.replace(tzinfo=UTC)
    return end > datetime.now(UTC)


async def require_active_subscription(db: AsyncSession, user: User) -> None:
    """Gate for patient-management features (spec 7, last bullet)."""
    if not settings.DOCTOR_SUBSCRIPTION_ENFORCED:
        return
    profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
    if profile is None:
        raise ForbiddenError("doctor profile required", code="doctor_profile_required")
    subscription = await db.scalar(
        sa.select(DoctorSubscription).where(DoctorSubscription.doctor_profile_id == profile.id)
    )
    if not subscription_is_active(subscription):
        raise ForbiddenError("an active subscription is required", code="subscription_required")


async def expire_subscriptions(db: AsyncSession) -> int:
    result = await db.execute(
        sa.update(DoctorSubscription)
        .where(
            DoctorSubscription.status.in_([SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIAL]),
            DoctorSubscription.current_period_end < datetime.now(UTC),
        )
        .values(status=SubscriptionStatus.EXPIRED)
    )
    return result.rowcount or 0
