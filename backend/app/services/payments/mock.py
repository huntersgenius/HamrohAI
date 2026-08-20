"""``PAYMENT_MODE=mock`` — a Click/Payme gateway that never leaves the process.

The Click and Payme merchant applications have not been approved yet, so there
are no credentials and no real checkout page. Without them the consultation flow
stops dead at "open the checkout URL": the payment is never confirmed, so the
consultation is never activated, so the 80/20 split, the wallet credit and the
24-hour SLA refund can none of them be reached end to end.

Mock mode fills exactly that gap, and nothing more:

* :func:`checkout_url` returns an internal URL instead of my.click.uz /
  checkout.paycom.uz.
* :func:`simulate_success` / :func:`simulate_failure` **synthesise the provider's
  own callback and run it through the real handler** — the real Click MD5
  signature over the real field order, the real Payme JSON-RPC method sequence.

That last point is the whole design. A mock that simply set
``payment.status = PAID`` would test nothing; this one exercises
``click.handle_prepare`` → ``click.handle_complete`` and
``payme.create_transaction`` → ``payme.perform_transaction`` exactly as the
gateway will call them, so what is verified now is the code that will run in
production. Only the network hop is removed.
"""

from __future__ import annotations

import dataclasses
import time
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.billing import Payment
from app.models.enums import PaymentProvider, PaymentStatus
from app.services.payments import click, payme

log = get_logger(__name__)

# Click's documented cancellation code for "payment failed on the user's side".
CLICK_USER_CANCELLED = -9


def checkout_url(payment: Payment) -> str:
    """Where the app sends the patient while there is no real gateway.

    The mobile client opens this exactly like a real checkout URL, so no client
    code differs between mock and real mode.
    """
    return f"{settings.IVR_WEBHOOK_BASE_URL}/api/v1/mock/checkout/{payment.id}"


def _sign_time() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def _click_request(
    payment: Payment,
    *,
    action: int,
    trans_id: str,
    merchant_prepare_id: str | None = None,
    error: int = 0,
) -> click.ClickRequest:
    """Build the form Click would POST, signed with the configured secret."""
    unsigned = click.ClickRequest(
        click_trans_id=trans_id,
        service_id=settings.CLICK_SERVICE_ID,
        click_paydoc_id=f"mock-paydoc-{trans_id}",
        merchant_trans_id=str(payment.id),
        merchant_prepare_id=merchant_prepare_id,
        amount=str(payment.amount_uzs),
        action=action,
        error=error,
        error_note=None,
        sign_time=_sign_time(),
        sign_string="",
    )
    # The dataclass is frozen (and slotted), so the signed form is a copy.
    return dataclasses.replace(unsigned, sign_string=click.build_signature(unsigned))


async def _simulate_click(db: AsyncSession, payment: Payment, *, succeed: bool) -> dict:
    # One transaction id per order, as a real gateway would: a re-press of the
    # pay button continues the same transaction instead of opening a second one.
    trans_id = payment.provider_transaction_id or f"mock{int(time.time() * 1000)}"

    prepare = await click.handle_prepare(db, _click_request(payment, action=0, trans_id=trans_id))
    if prepare.get("error") != click.SUCCESS:
        return {"stage": "prepare", "provider": "click", "response": prepare}

    complete = await click.handle_complete(
        db,
        _click_request(
            payment,
            action=1,
            trans_id=trans_id,
            merchant_prepare_id=prepare.get("merchant_prepare_id"),
            error=0 if succeed else CLICK_USER_CANCELLED,
        ),
    )
    return {"stage": "complete", "provider": "click", "response": complete}


async def _simulate_payme(db: AsyncSession, payment: Payment, *, succeed: bool) -> dict:
    transaction_id = payment.provider_transaction_id or uuid.uuid4().hex[:24]
    account = {"order_id": str(payment.id)}

    create = await payme.dispatch(
        db,
        payme.PaymeContext(
            method="CreateTransaction",
            params={
                "id": transaction_id,
                "time": int(time.time() * 1000),
                "amount": payment.amount_minor,
                "account": account,
            },
            request_id=1,
        ),
    )

    method = "PerformTransaction" if succeed else "CancelTransaction"
    params: dict = {"id": transaction_id}
    if not succeed:
        params["reason"] = 1  # Payme: "the payer did not complete the payment"

    final = await payme.dispatch(
        db, payme.PaymeContext(method=method, params=params, request_id=2)
    )
    return {
        "stage": method,
        "provider": "payme",
        "response": {"create": create.get("result"), "final": final.get("result")},
    }


async def _simulate(db: AsyncSession, payment: Payment, *, succeed: bool) -> dict:
    from app.services.mocks import outbox

    if payment.status == PaymentStatus.PAID:
        # A settled order is never re-driven through the protocol; both
        # gateways would answer from their own records. Returning here keeps
        # the simulator idempotent, which is the property the real callbacks
        # are also required to have.
        return {
            "stage": "already_paid",
            "provider": payment.provider.value,
            "response": {"payment_status": payment.status.value},
        }

    if payment.provider == PaymentProvider.CLICK:
        result = await _simulate_click(db, payment, succeed=succeed)
    else:
        result = await _simulate_payme(db, payment, succeed=succeed)

    outbox.record(
        "payment",
        str(payment.id),
        f"{result['provider']} {'success' if succeed else 'failure'} simulated",
        amount_uzs=payment.amount_uzs,
        purpose=payment.purpose.value,
        **result,
    )
    log.info(
        "payments.mock_simulated",
        payment_id=str(payment.id),
        provider=result["provider"],
        succeed=succeed,
    )
    return result


async def simulate_success(db: AsyncSession, payment: Payment) -> dict:
    """Drive the payment to PAID through the provider's real callback path."""
    return await _simulate(db, payment, succeed=True)


async def simulate_failure(db: AsyncSession, payment: Payment) -> dict:
    """Same path, but the provider reports the payment as cancelled."""
    return await _simulate(db, payment, succeed=False)
