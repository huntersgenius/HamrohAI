"""Payments (Click / Payme), doctor wallet and payout requests (spec 7)."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    JSONType,
    TimestampMixin,
    TimestampType,
    UUIDPrimaryKeyMixin,
    UUIDType,
)
from app.models.enums import (
    PaymentProvider,
    PaymentPurpose,
    PaymentStatus,
    PayoutStatus,
    WalletTxnType,
    enum_column,
)


class Payment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A payment attempt against Click or Payme.

    Both providers drive the state machine through their own webhooks, so this
    row is the single reconciliation point: ``provider_transaction_id`` is unique
    per provider and every callback is idempotent on it.
    """

    __tablename__ = "payments"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[PaymentProvider] = mapped_column(
        enum_column(PaymentProvider, "payment_provider"), nullable=False
    )
    purpose: Mapped[PaymentPurpose] = mapped_column(
        enum_column(PaymentPurpose, "payment_purpose"), nullable=False
    )
    status: Mapped[PaymentStatus] = mapped_column(
        enum_column(PaymentStatus, "payment_status"),
        default=PaymentStatus.CREATED,
        nullable=False,
        index=True,
    )
    amount_uzs: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    # Payme works in tiyin (1 UZS = 100 tiyin); stored to reconcile exactly.
    amount_minor: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)

    consultation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("consultations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    subscription_plan: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)

    provider_transaction_id: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    provider_state: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    provider_payload: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)

    prepared_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    cancel_reason: Mapped[int | None] = mapped_column(sa.Integer, nullable=True)

    consultation: Mapped[Consultation | None] = relationship(  # noqa: F821
        back_populates="payments"
    )

    __table_args__ = (
        sa.UniqueConstraint("provider", "provider_transaction_id", name="uq_payment_provider_txn"),
        sa.CheckConstraint("amount_uzs >= 0", name="ck_payment_amount_nonneg"),
    )

    @property
    def is_paid(self) -> bool:
        return self.status == PaymentStatus.PAID


class Wallet(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Doctor's internal balance. Not real money movement — an internal ledger
    that manual payouts settle against (spec 7)."""

    __tablename__ = "wallets"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    balance_uzs: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    lifetime_earned_uzs: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)
    lifetime_paid_out_uzs: Mapped[int] = mapped_column(sa.Integer, default=0, nullable=False)

    transactions: Mapped[list[WalletTransaction]] = relationship(
        back_populates="wallet", cascade="all, delete-orphan"
    )

    __table_args__ = (sa.CheckConstraint("balance_uzs >= 0", name="ck_wallet_balance_nonneg"),)


class WalletTransaction(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only ledger entry. ``balance_after`` makes statements auditable."""

    __tablename__ = "wallet_transactions"

    wallet_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("wallets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[WalletTxnType] = mapped_column(
        enum_column(WalletTxnType, "wallet_txn_type"), nullable=False
    )
    # Positive = credit, negative = debit.
    amount_uzs: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    balance_after_uzs: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    consultation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("consultations.id", ondelete="SET NULL"), nullable=True
    )
    payout_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("payout_requests.id", ondelete="SET NULL"), nullable=True
    )
    description: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    # Guards against double-crediting the same event.
    idempotency_key: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)

    wallet: Mapped[Wallet] = relationship(back_populates="transactions")

    __table_args__ = (sa.UniqueConstraint("idempotency_key", name="uq_wallet_txn_idempotency"),)


class PayoutRequest(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Withdrawal request. Processed manually in the MVP (spec 7)."""

    __tablename__ = "payout_requests"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_uzs: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[PayoutStatus] = mapped_column(
        enum_column(PayoutStatus, "payout_status"),
        default=PayoutStatus.REQUESTED,
        nullable=False,
        index=True,
    )
    # Only the last four digits are retained; full PANs are never stored.
    card_last4: Mapped[str | None] = mapped_column(sa.String(4), nullable=True)
    card_holder: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)
    # Encrypted destination reference handed to the finance operator out of band.
    destination_ref: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    note: Mapped[str | None] = mapped_column(sa.Text, nullable=True)

    __table_args__ = (sa.CheckConstraint("amount_uzs > 0", name="ck_payout_amount_positive"),)
