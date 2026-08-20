"""Payme (Paycom) Merchant API — JSON-RPC 2.0.

Payme drives a two-phase transaction: ``CreateTransaction`` reserves, then
``PerformTransaction`` settles. Amounts are in **tiyin** (1 UZS = 100 tiyin).
Authentication is HTTP Basic with the username ``Paycom`` and the merchant key.

Every method must be idempotent on ``params.id`` — Payme retries aggressively and
treats a differing response to a repeated call as a protocol violation.
"""

from __future__ import annotations

import base64
import binascii
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import constant_time_equals
from app.models.billing import Payment
from app.models.enums import PaymentProvider, PaymentStatus

log = get_logger(__name__)

# Payme JSON-RPC error codes.
ERR_TRANSPORT = -32300
ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32400
ERR_INSUFFICIENT_PRIVILEGE = -32504
ERR_ORDER_NOT_FOUND = -31050
ERR_INVALID_AMOUNT = -31001
ERR_CANNOT_PERFORM = -31008
ERR_TRANSACTION_NOT_FOUND = -31003
ERR_CANNOT_CANCEL = -31007

# Payme transaction states.
STATE_CREATED = 1
STATE_COMPLETED = 2
STATE_CANCELLED = -1
STATE_CANCELLED_AFTER_COMPLETE = -2

# Transactions unconfirmed for longer than this are auto-cancelled by Payme.
TRANSACTION_TIMEOUT_MS = 12 * 60 * 60 * 1000


class PaymeError(Exception):
    def __init__(self, code: int, message: str, data: str | None = None) -> None:
        self.code = code
        self.message = message
        self.data = data
        super().__init__(message)

    def to_response(self, request_id: Any) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {
                "code": self.code,
                # Payme requires the message in three locales.
                "message": {"uz": self.message, "ru": self.message, "en": self.message},
                "data": self.data,
            },
        }


@dataclass(frozen=True, slots=True)
class PaymeContext:
    method: str
    params: dict
    request_id: Any


def verify_auth(authorization_header: str | None) -> bool:
    """HTTP Basic ``Paycom:<merchant key>``."""
    if not authorization_header or not authorization_header.lower().startswith("basic "):
        return False
    try:
        decoded = base64.b64decode(authorization_header.split(" ", 1)[1]).decode()
    except (binascii.Error, UnicodeDecodeError, IndexError):
        return False
    login, _, key = decoded.partition(":")
    if login != "Paycom":
        return False
    if constant_time_equals(key, settings.PAYME_KEY):
        return True
    # The test key is only honoured outside production.
    return bool(
        settings.PAYME_TEST_KEY
        and not settings.is_production
        and constant_time_equals(key, settings.PAYME_TEST_KEY)
    )


def checkout_url(payment: Payment) -> str:
    """Payme opens a checkout encoded as base64 of ``m=..;ac.order_id=..;a=..``."""
    raw = (
        f"m={settings.PAYME_MERCHANT_ID};"
        f"ac.order_id={payment.id};"
        f"a={payment.amount_minor};"
        f"c={settings.IVR_WEBHOOK_BASE_URL}/payments/{payment.id}/return"
    )
    encoded = base64.b64encode(raw.encode()).decode()
    return f"{settings.PAYME_CHECKOUT_URL}/{encoded}"


def _now_ms() -> int:
    return int(time.time() * 1000)


def _to_ms(value: datetime | None) -> int:
    if value is None:
        return 0
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    return int(aware.timestamp() * 1000)


async def dispatch(db: AsyncSession, context: PaymeContext) -> dict:
    handlers = {
        "CheckPerformTransaction": check_perform_transaction,
        "CreateTransaction": create_transaction,
        "PerformTransaction": perform_transaction,
        "CancelTransaction": cancel_transaction,
        "CheckTransaction": check_transaction,
        "GetStatement": get_statement,
    }
    handler = handlers.get(context.method)
    if handler is None:
        raise PaymeError(ERR_METHOD_NOT_FOUND, "Method not found")
    result = await handler(db, context.params)
    return {"jsonrpc": "2.0", "id": context.request_id, "result": result}


async def _load_by_order(db: AsyncSession, params: dict) -> Payment:
    account = params.get("account") or {}
    order_id = account.get("order_id")
    try:
        payment_id = uuid.UUID(str(order_id))
    except (ValueError, TypeError):
        raise PaymeError(ERR_ORDER_NOT_FOUND, "Order not found", "order_id") from None

    payment = await db.scalar(
        sa.select(Payment).where(
            Payment.id == payment_id, Payment.provider == PaymentProvider.PAYME
        )
    )
    if payment is None:
        raise PaymeError(ERR_ORDER_NOT_FOUND, "Order not found", "order_id")
    return payment


async def _load_by_transaction(db: AsyncSession, params: dict) -> Payment:
    transaction_id = params.get("id")
    payment = await db.scalar(
        sa.select(Payment).where(
            Payment.provider == PaymentProvider.PAYME,
            Payment.provider_transaction_id == str(transaction_id),
        )
    )
    if payment is None:
        raise PaymeError(ERR_TRANSACTION_NOT_FOUND, "Transaction not found")
    return payment


def _assert_amount(payment: Payment, params: dict) -> None:
    if int(params.get("amount") or 0) != payment.amount_minor:
        raise PaymeError(ERR_INVALID_AMOUNT, "Invalid amount", "amount")


async def check_perform_transaction(db: AsyncSession, params: dict) -> dict:
    payment = await _load_by_order(db, params)
    _assert_amount(payment, params)
    if payment.status in (PaymentStatus.PAID, PaymentStatus.REFUNDED):
        raise PaymeError(ERR_CANNOT_PERFORM, "Order already processed")
    if payment.status == PaymentStatus.CANCELLED:
        raise PaymeError(ERR_CANNOT_PERFORM, "Order cancelled")
    return {"allow": True}


async def create_transaction(db: AsyncSession, params: dict) -> dict:
    transaction_id = str(params.get("id"))
    payment = await _load_by_order(db, params)
    _assert_amount(payment, params)

    # Repeat call for the same transaction: echo the stored state.
    if payment.provider_transaction_id == transaction_id:
        if payment.status == PaymentStatus.CANCELLED:
            raise PaymeError(ERR_CANNOT_PERFORM, "Transaction cancelled")
        return {
            "create_time": _to_ms(payment.prepared_at),
            "transaction": str(payment.id),
            "state": STATE_COMPLETED if payment.is_paid else STATE_CREATED,
        }

    # A different transaction already owns this order.
    if payment.provider_transaction_id and payment.status in (
        PaymentStatus.PENDING,
        PaymentStatus.PAID,
    ):
        raise PaymeError(ERR_CANNOT_PERFORM, "Order is busy with another transaction")

    if payment.status in (PaymentStatus.CANCELLED, PaymentStatus.REFUNDED):
        raise PaymeError(ERR_CANNOT_PERFORM, "Order cannot be paid")

    now = datetime.now(UTC)
    payment.provider_transaction_id = transaction_id
    payment.status = PaymentStatus.PENDING
    payment.prepared_at = now
    payment.provider_state = str(STATE_CREATED)
    payment.provider_payload = {"payme_time": params.get("time")}
    await db.flush()

    return {
        "create_time": _to_ms(now),
        "transaction": str(payment.id),
        "state": STATE_CREATED,
    }


async def perform_transaction(db: AsyncSession, params: dict) -> dict:
    payment = await _load_by_transaction(db, params)

    if payment.status == PaymentStatus.PAID:
        return {
            "transaction": str(payment.id),
            "perform_time": _to_ms(payment.paid_at),
            "state": STATE_COMPLETED,
        }
    if payment.status in (PaymentStatus.CANCELLED, PaymentStatus.REFUNDED):
        raise PaymeError(ERR_CANNOT_PERFORM, "Transaction cancelled")

    # Payme expects us to time out stale reservations ourselves.
    if payment.prepared_at and _now_ms() - _to_ms(payment.prepared_at) > TRANSACTION_TIMEOUT_MS:
        payment.status = PaymentStatus.CANCELLED
        payment.cancelled_at = datetime.now(UTC)
        payment.cancel_reason = 4
        payment.provider_state = str(STATE_CANCELLED)
        await db.flush()
        from app.services.billing import on_payment_cancelled

        await on_payment_cancelled(db, payment)
        raise PaymeError(ERR_CANNOT_PERFORM, "Transaction timed out")

    now = datetime.now(UTC)
    payment.status = PaymentStatus.PAID
    payment.paid_at = now
    payment.provider_state = str(STATE_COMPLETED)
    await db.flush()

    from app.services.billing import on_payment_succeeded

    await on_payment_succeeded(db, payment)

    return {
        "transaction": str(payment.id),
        "perform_time": _to_ms(now),
        "state": STATE_COMPLETED,
    }


async def cancel_transaction(db: AsyncSession, params: dict) -> dict:
    payment = await _load_by_transaction(db, params)
    reason = params.get("reason")
    now = datetime.now(UTC)

    if payment.status in (PaymentStatus.CANCELLED, PaymentStatus.REFUNDED):
        state = (
            STATE_CANCELLED_AFTER_COMPLETE
            if payment.status == PaymentStatus.REFUNDED
            else STATE_CANCELLED
        )
        return {
            "transaction": str(payment.id),
            "cancel_time": _to_ms(payment.cancelled_at or payment.refunded_at),
            "state": state,
        }

    if payment.status == PaymentStatus.PAID:
        # Cancelling a settled payment is a refund (state -2).
        payment.status = PaymentStatus.REFUNDED
        payment.refunded_at = now
        payment.cancel_reason = reason
        payment.provider_state = str(STATE_CANCELLED_AFTER_COMPLETE)
        await db.flush()
        from app.services.billing import on_payment_refunded

        await on_payment_refunded(db, payment)
        return {
            "transaction": str(payment.id),
            "cancel_time": _to_ms(now),
            "state": STATE_CANCELLED_AFTER_COMPLETE,
        }

    payment.status = PaymentStatus.CANCELLED
    payment.cancelled_at = now
    payment.cancel_reason = reason
    payment.provider_state = str(STATE_CANCELLED)
    await db.flush()
    from app.services.billing import on_payment_cancelled

    await on_payment_cancelled(db, payment)
    return {
        "transaction": str(payment.id),
        "cancel_time": _to_ms(now),
        "state": STATE_CANCELLED,
    }


async def check_transaction(db: AsyncSession, params: dict) -> dict:
    payment = await _load_by_transaction(db, params)
    if payment.status == PaymentStatus.PAID:
        state = STATE_COMPLETED
    elif payment.status == PaymentStatus.REFUNDED:
        state = STATE_CANCELLED_AFTER_COMPLETE
    elif payment.status == PaymentStatus.CANCELLED:
        state = STATE_CANCELLED
    else:
        state = STATE_CREATED
    return {
        "create_time": _to_ms(payment.prepared_at),
        "perform_time": _to_ms(payment.paid_at),
        "cancel_time": _to_ms(payment.cancelled_at or payment.refunded_at),
        "transaction": str(payment.id),
        "state": state,
        "reason": payment.cancel_reason,
    }


async def get_statement(db: AsyncSession, params: dict) -> dict:
    """Reconciliation: every Payme transaction in the requested window."""
    start = datetime.fromtimestamp(int(params.get("from", 0)) / 1000, tz=UTC)
    end = datetime.fromtimestamp(int(params.get("to", 0)) / 1000, tz=UTC)
    payments = list(
        (
            await db.scalars(
                sa.select(Payment).where(
                    Payment.provider == PaymentProvider.PAYME,
                    Payment.provider_transaction_id.is_not(None),
                    Payment.created_at >= start,
                    Payment.created_at <= end,
                )
            )
        ).all()
    )
    return {
        "transactions": [
            {
                "id": payment.provider_transaction_id,
                "time": _to_ms(payment.prepared_at),
                "amount": payment.amount_minor,
                "account": {"order_id": str(payment.id)},
                "create_time": _to_ms(payment.prepared_at),
                "perform_time": _to_ms(payment.paid_at),
                "cancel_time": _to_ms(payment.cancelled_at or payment.refunded_at),
                "transaction": str(payment.id),
                "state": STATE_COMPLETED if payment.is_paid else STATE_CREATED,
                "reason": payment.cancel_reason,
            }
            for payment in payments
        ]
    }
