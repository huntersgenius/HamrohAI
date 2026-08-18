"""Wallet, payout and payment contracts (spec 4.2 tab 3, spec 7)."""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import (
    PaymentProvider,
    PaymentPurpose,
    PaymentStatus,
    PayoutStatus,
    SubscriptionPlan,
    WalletTxnType,
)
from app.schemas.common import ORMModel


class WalletResponse(BaseModel):
    balance_uzs: int
    lifetime_earned_uzs: int
    lifetime_paid_out_uzs: int
    min_payout_uzs: int
    can_request_payout: bool
    currency: str = "UZS"


class WalletTransactionResponse(ORMModel):
    id: uuid.UUID
    type: WalletTxnType
    amount_uzs: int
    balance_after_uzs: int
    description: str | None
    consultation_id: uuid.UUID | None
    counterparty_name: str | None = None
    created_at: datetime


class PayoutRequestCreate(BaseModel):
    amount_uzs: int = Field(gt=0)
    card_number: str = Field(min_length=12, max_length=24)
    card_holder: str = Field(min_length=2, max_length=160)

    @field_validator("card_number")
    @classmethod
    def _digits(cls, v: str) -> str:
        digits = "".join(ch for ch in v if ch.isdigit())
        if len(digits) < 12:
            raise ValueError("invalid card number")
        return digits


class PayoutRequestResponse(ORMModel):
    id: uuid.UUID
    amount_uzs: int
    status: PayoutStatus
    card_last4: str | None
    card_holder: str | None
    note: str | None
    created_at: datetime
    processed_at: datetime | None


class PaymentResponse(ORMModel):
    id: uuid.UUID
    provider: PaymentProvider
    purpose: PaymentPurpose
    status: PaymentStatus
    amount_uzs: int
    consultation_id: uuid.UUID | None
    created_at: datetime
    paid_at: datetime | None


class SubscriptionCheckoutRequest(BaseModel):
    plan: SubscriptionPlan
    provider: PaymentProvider


class CheckoutResponse(BaseModel):
    payment_id: uuid.UUID
    checkout_url: str
    amount_uzs: int
    provider: PaymentProvider


class SubscriptionStatusResponse(BaseModel):
    status: str
    plan: str | None
    current_period_end: datetime | None
    is_active: bool
    monthly_price_uzs: int
    yearly_price_uzs: int
