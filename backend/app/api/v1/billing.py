"""Wallet, payouts and doctor subscription endpoints (spec 4.2 tab 3, spec 7)."""

from __future__ import annotations

import sqlalchemy as sa
from fastapi import APIRouter, status

from app.api.deps import DbSession, DoctorUser, Pagination, VerifiedDoctor
from app.core.config import settings
from app.core.errors import NotFoundError
from app.models.billing import PayoutRequest, WalletTransaction
from app.models.consultation import Consultation
from app.models.enums import PaymentPurpose, SubscriptionPlan
from app.models.profile import DoctorProfile, DoctorSubscription
from app.models.user import User
from app.schemas.billing import (
    CheckoutResponse,
    PayoutRequestCreate,
    PayoutRequestResponse,
    SubscriptionCheckoutRequest,
    SubscriptionStatusResponse,
    WalletResponse,
    WalletTransactionResponse,
)
from app.schemas.common import Page
from app.services import billing as service

router = APIRouter(prefix="/wallet", tags=["billing"])


@router.get("", response_model=WalletResponse)
async def get_wallet(db: DbSession, user: VerifiedDoctor) -> WalletResponse:
    wallet = await service.get_or_create_wallet(db, user.id)
    await db.commit()
    return WalletResponse(
        balance_uzs=wallet.balance_uzs,
        lifetime_earned_uzs=wallet.lifetime_earned_uzs,
        lifetime_paid_out_uzs=wallet.lifetime_paid_out_uzs,
        min_payout_uzs=settings.WALLET_MIN_PAYOUT_UZS,
        # The "Pul yechish" button only activates above the threshold.
        can_request_payout=wallet.balance_uzs >= settings.WALLET_MIN_PAYOUT_UZS,
        currency=settings.CURRENCY,
    )


@router.get("/transactions", response_model=Page[WalletTransactionResponse])
async def list_transactions(
    db: DbSession, user: VerifiedDoctor, page: Pagination
) -> Page[WalletTransactionResponse]:
    wallet = await service.get_or_create_wallet(db, user.id)
    await db.commit()

    total = (
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(WalletTransaction)
            .where(WalletTransaction.wallet_id == wallet.id)
        )
    ) or 0
    rows = (
        await db.scalars(
            sa.select(WalletTransaction)
            .where(WalletTransaction.wallet_id == wallet.id)
            .order_by(WalletTransaction.created_at.desc())
            .limit(page.limit)
            .offset(page.offset)
        )
    ).all()

    items = []
    for transaction in rows:
        response = WalletTransactionResponse.model_validate(transaction)
        if transaction.consultation_id:
            consultation = await db.get(Consultation, transaction.consultation_id)
            if consultation is not None:
                patient = await db.get(User, consultation.patient_user_id)
                response.counterparty_name = patient.full_name if patient else None
        items.append(response)
    return Page(items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("/payouts", response_model=PayoutRequestResponse, status_code=status.HTTP_201_CREATED)
async def request_payout(
    payload: PayoutRequestCreate, db: DbSession, user: VerifiedDoctor
) -> PayoutRequestResponse:
    """ "Pul yechish" — processed manually by finance in the MVP."""
    payout = await service.request_payout(
        db,
        user=user,
        amount_uzs=payload.amount_uzs,
        card_number=payload.card_number,
        card_holder=payload.card_holder,
    )
    await db.commit()
    await db.refresh(payout)
    return PayoutRequestResponse.model_validate(payout)


@router.get("/payouts", response_model=list[PayoutRequestResponse])
async def list_payouts(db: DbSession, user: VerifiedDoctor) -> list[PayoutRequestResponse]:
    payouts = (
        await db.scalars(
            sa.select(PayoutRequest)
            .where(PayoutRequest.user_id == user.id)
            .order_by(PayoutRequest.created_at.desc())
            .limit(50)
        )
    ).all()
    return [PayoutRequestResponse.model_validate(p) for p in payouts]


# --------------------------------------------------------------- subscriptions
subscription_router = APIRouter(prefix="/subscription", tags=["billing"])


@subscription_router.get("", response_model=SubscriptionStatusResponse)
async def get_subscription(db: DbSession, user: DoctorUser) -> SubscriptionStatusResponse:
    profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
    if profile is None:
        raise NotFoundError("doctor profile not found", code="profile_not_found")

    subscription = await db.scalar(
        sa.select(DoctorSubscription).where(DoctorSubscription.doctor_profile_id == profile.id)
    )
    return SubscriptionStatusResponse(
        status=subscription.status.value if subscription else "none",
        plan=subscription.plan.value if subscription else None,
        current_period_end=subscription.current_period_end if subscription else None,
        is_active=service.subscription_is_active(subscription),
        monthly_price_uzs=settings.DOCTOR_SUBSCRIPTION_MONTHLY_UZS,
        yearly_price_uzs=settings.DOCTOR_SUBSCRIPTION_YEARLY_UZS,
    )


@subscription_router.post("/checkout", response_model=CheckoutResponse)
async def checkout_subscription(
    payload: SubscriptionCheckoutRequest, db: DbSession, user: DoctorUser
) -> CheckoutResponse:
    plan = SubscriptionPlan(payload.plan)
    payment = await service.create_payment(
        db,
        user=user,
        provider=payload.provider,
        purpose=PaymentPurpose.SUBSCRIPTION,
        amount_uzs=service.subscription_price(plan),
        subscription_plan=plan.value,
    )
    await db.commit()
    return CheckoutResponse(
        payment_id=payment.id,
        checkout_url=service.build_checkout_url(payment),
        amount_uzs=payment.amount_uzs,
        provider=payment.provider,
    )
