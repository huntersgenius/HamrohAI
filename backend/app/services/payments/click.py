"""Click (click.uz) Merchant API — Prepare / Complete protocol.

Click calls two endpoints on us: ``Prepare`` (action=0) reserves the payment and
``Complete`` (action=1) confirms or cancels it. Both are authenticated with a
SHA-1 signature over a fixed field order; both must be idempotent because Click
retries.

Error codes are Click's own and must be returned verbatim — the gateway branches
on them.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlencode

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.billing import Payment
from app.models.enums import PaymentProvider, PaymentStatus

log = get_logger(__name__)

# Click protocol error codes.
SUCCESS = 0
ERR_SIGN_CHECK_FAILED = -1
ERR_INCORRECT_AMOUNT = -2
ERR_ACTION_NOT_FOUND = -3
ERR_ALREADY_PAID = -4
ERR_USER_NOT_FOUND = -5
ERR_TRANSACTION_NOT_FOUND = -6
ERR_FAILED_TO_UPDATE = -7
ERR_ERROR_IN_REQUEST = -8
ERR_TRANSACTION_CANCELLED = -9

ACTION_PREPARE = 0
ACTION_COMPLETE = 1


@dataclass(frozen=True, slots=True)
class ClickRequest:
    click_trans_id: str
    service_id: str
    click_paydoc_id: str | None
    merchant_trans_id: str
    merchant_prepare_id: str | None
    amount: str
    action: int
    error: int
    error_note: str | None
    sign_time: str
    sign_string: str

    @classmethod
    def from_form(cls, form: dict) -> ClickRequest:
        def get(key: str) -> str | None:
            value = form.get(key)
            return str(value) if value is not None else None

        return cls(
            click_trans_id=get("click_trans_id") or "",
            service_id=get("service_id") or "",
            click_paydoc_id=get("click_paydoc_id"),
            merchant_trans_id=get("merchant_trans_id") or "",
            merchant_prepare_id=get("merchant_prepare_id"),
            amount=get("amount") or "0",
            action=int(form.get("action") or 0),
            error=int(form.get("error") or 0),
            error_note=get("error_note"),
            sign_time=get("sign_time") or "",
            sign_string=get("sign_string") or "",
        )


def build_signature(request: ClickRequest) -> str:
    """MD5 over the Click-defined field order.

    Prepare omits ``merchant_prepare_id``; Complete includes it. Getting this
    order wrong is the most common Click integration failure.
    """
    parts = [
        request.click_trans_id,
        request.service_id,
        settings.CLICK_SECRET_KEY,
        request.merchant_trans_id,
    ]
    if request.action == ACTION_COMPLETE:
        parts.append(request.merchant_prepare_id or "")
    parts += [request.amount, str(request.action), request.sign_time]
    return hashlib.md5("".join(parts).encode()).hexdigest()  # noqa: S324 - required by Click


def verify_signature(request: ClickRequest) -> bool:
    import hmac

    return hmac.compare_digest(build_signature(request), (request.sign_string or "").lower())


def checkout_url(payment: Payment) -> str:
    """URL the app opens so the patient can pay."""
    params = {
        "service_id": settings.CLICK_SERVICE_ID,
        "merchant_id": settings.CLICK_MERCHANT_ID,
        "amount": payment.amount_uzs,
        "transaction_param": str(payment.id),
        "return_url": f"{settings.IVR_WEBHOOK_BASE_URL}/payments/{payment.id}/return",
    }
    return f"{settings.CLICK_CHECKOUT_URL}?{urlencode(params)}"


def _response(error: int, note: str, **extra) -> dict:
    return {"error": error, "error_note": note, **extra}


async def handle_prepare(db: AsyncSession, request: ClickRequest) -> dict:
    """action=0 — validate and reserve the payment."""
    if not verify_signature(request):
        log.warning("click.bad_signature", trans_id=request.click_trans_id)
        return _response(ERR_SIGN_CHECK_FAILED, "SIGN CHECK FAILED")

    payment = await _load_payment(db, request.merchant_trans_id)
    if payment is None:
        return _response(ERR_USER_NOT_FOUND, "Payment not found")

    if int(float(request.amount)) != payment.amount_uzs:
        return _response(ERR_INCORRECT_AMOUNT, "Incorrect amount")

    if payment.status == PaymentStatus.PAID:
        return _response(ERR_ALREADY_PAID, "Already paid")
    if payment.status == PaymentStatus.CANCELLED:
        return _response(ERR_TRANSACTION_CANCELLED, "Transaction cancelled")

    payment.status = PaymentStatus.PENDING
    payment.provider_transaction_id = request.click_trans_id
    payment.prepared_at = datetime.now(UTC)
    payment.provider_payload = {"click_paydoc_id": request.click_paydoc_id}
    await db.flush()

    return _response(
        SUCCESS,
        "Success",
        click_trans_id=request.click_trans_id,
        merchant_trans_id=request.merchant_trans_id,
        merchant_prepare_id=str(payment.id),
    )


async def handle_complete(db: AsyncSession, request: ClickRequest) -> dict:
    """action=1 — confirm the payment, or record the cancellation."""
    if not verify_signature(request):
        log.warning("click.bad_signature", trans_id=request.click_trans_id)
        return _response(ERR_SIGN_CHECK_FAILED, "SIGN CHECK FAILED")

    payment = await _load_payment(db, request.merchant_trans_id)
    if payment is None:
        return _response(ERR_USER_NOT_FOUND, "Payment not found")
    if str(payment.id) != (request.merchant_prepare_id or ""):
        return _response(ERR_TRANSACTION_NOT_FOUND, "Transaction not found")

    # Click signals a failed payment with a negative `error` on Complete.
    if request.error < 0:
        if payment.status != PaymentStatus.PAID:
            payment.status = PaymentStatus.CANCELLED
            payment.cancelled_at = datetime.now(UTC)
            payment.cancel_reason = request.error
            await db.flush()
            await _on_cancelled(db, payment)
        return _response(ERR_TRANSACTION_CANCELLED, "Transaction cancelled")

    if int(float(request.amount)) != payment.amount_uzs:
        return _response(ERR_INCORRECT_AMOUNT, "Incorrect amount")

    # Idempotent: a retried Complete for an already-paid order must succeed
    # without crediting anything twice.
    if payment.status == PaymentStatus.PAID:
        return _response(
            SUCCESS,
            "Success",
            click_trans_id=request.click_trans_id,
            merchant_trans_id=request.merchant_trans_id,
            merchant_confirm_id=str(payment.id),
        )

    payment.status = PaymentStatus.PAID
    payment.paid_at = datetime.now(UTC)
    payment.provider_state = "confirmed"
    await db.flush()
    await _on_paid(db, payment)

    return _response(
        SUCCESS,
        "Success",
        click_trans_id=request.click_trans_id,
        merchant_trans_id=request.merchant_trans_id,
        merchant_confirm_id=str(payment.id),
    )


async def _load_payment(db: AsyncSession, merchant_trans_id: str) -> Payment | None:
    try:
        payment_id = uuid.UUID(merchant_trans_id)
    except (ValueError, AttributeError):
        return None
    return await db.scalar(
        sa.select(Payment).where(
            Payment.id == payment_id, Payment.provider == PaymentProvider.CLICK
        )
    )


async def _on_paid(db: AsyncSession, payment: Payment) -> None:
    from app.services.billing import on_payment_succeeded

    await on_payment_succeeded(db, payment)


async def _on_cancelled(db: AsyncSession, payment: Payment) -> None:
    from app.services.billing import on_payment_cancelled

    await on_payment_cancelled(db, payment)
