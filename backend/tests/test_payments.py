"""Click and Payme merchant protocol conformance.

Both gateways retry aggressively and branch on exact error codes, so the tests
focus on signature verification, idempotency and state-machine correctness
rather than on the happy path alone.
"""

from __future__ import annotations

import base64
import hashlib
import time

import pytest

from app.core.config import settings
from app.models.billing import Payment
from app.models.enums import PaymentProvider, PaymentPurpose, PaymentStatus
from app.services.billing import create_payment
from app.services.payments import click, payme
from tests.conftest import make_patient


async def _payment(db, provider: PaymentProvider, amount: int = 50_000) -> Payment:
    patient = await make_patient(db, f"+99890130{int(time.time() * 1000) % 10000:04d}")
    payment = await create_payment(
        db,
        user=patient,
        provider=provider,
        purpose=PaymentPurpose.SUBSCRIPTION,
        amount_uzs=amount,
    )
    await db.commit()
    return payment


def _click_request(payment: Payment, action: int, **overrides) -> click.ClickRequest:
    form = {
        "click_trans_id": "12345",
        "service_id": settings.CLICK_SERVICE_ID or "svc",
        "click_paydoc_id": "999",
        "merchant_trans_id": str(payment.id),
        "merchant_prepare_id": str(payment.id) if action == 1 else None,
        "amount": str(payment.amount_uzs),
        "action": action,
        "error": 0,
        "error_note": "",
        "sign_time": "2026-01-01 10:00:00",
        "sign_string": "",
    }
    form.update(overrides)
    request = click.ClickRequest.from_form(form)
    if not form.get("sign_string"):
        request = click.ClickRequest.from_form(
            {**form, "sign_string": click.build_signature(request)}
        )
    return request


class TestClick:
    async def test_prepare_reserves_the_payment(self, db) -> None:
        payment = await _payment(db, PaymentProvider.CLICK)
        result = await click.handle_prepare(db, _click_request(payment, 0))
        await db.commit()

        assert result["error"] == click.SUCCESS
        await db.refresh(payment)
        assert payment.status == PaymentStatus.PENDING

    async def test_bad_signature_is_rejected(self, db) -> None:
        payment = await _payment(db, PaymentProvider.CLICK)
        request = _click_request(payment, 0, sign_string="deadbeef")
        result = await click.handle_prepare(db, request)
        assert result["error"] == click.ERR_SIGN_CHECK_FAILED

    async def test_amount_mismatch_is_rejected(self, db) -> None:
        payment = await _payment(db, PaymentProvider.CLICK, amount=50_000)
        request = _click_request(payment, 0, amount="1")
        result = await click.handle_prepare(db, request)
        assert result["error"] == click.ERR_INCORRECT_AMOUNT

    async def test_complete_marks_paid(self, db) -> None:
        payment = await _payment(db, PaymentProvider.CLICK)
        await click.handle_prepare(db, _click_request(payment, 0))
        await db.commit()

        result = await click.handle_complete(db, _click_request(payment, 1))
        await db.commit()
        assert result["error"] == click.SUCCESS

        await db.refresh(payment)
        assert payment.status == PaymentStatus.PAID
        assert payment.paid_at is not None

    async def test_repeated_complete_is_idempotent(self, db) -> None:
        """Click retries; a second Complete must succeed without double-crediting."""
        payment = await _payment(db, PaymentProvider.CLICK)
        await click.handle_prepare(db, _click_request(payment, 0))
        await db.commit()
        await click.handle_complete(db, _click_request(payment, 1))
        await db.commit()
        paid_at = payment.paid_at

        result = await click.handle_complete(db, _click_request(payment, 1))
        await db.commit()
        assert result["error"] == click.SUCCESS

        await db.refresh(payment)
        assert payment.paid_at == paid_at

    async def test_negative_error_cancels(self, db) -> None:
        payment = await _payment(db, PaymentProvider.CLICK)
        await click.handle_prepare(db, _click_request(payment, 0))
        await db.commit()

        result = await click.handle_complete(db, _click_request(payment, 1, error=-5001))
        await db.commit()
        assert result["error"] == click.ERR_TRANSACTION_CANCELLED

        await db.refresh(payment)
        assert payment.status == PaymentStatus.CANCELLED

    async def test_unknown_order_is_reported(self, db) -> None:
        payment = await _payment(db, PaymentProvider.CLICK)
        request = _click_request(payment, 0, merchant_trans_id="not-a-uuid")
        result = await click.handle_prepare(db, request)
        # Signature covers merchant_trans_id, so tampering fails there first.
        assert result["error"] in (click.ERR_SIGN_CHECK_FAILED, click.ERR_USER_NOT_FOUND)


class TestPaymeAuth:
    def test_valid_basic_auth_accepted(self) -> None:
        token = base64.b64encode(f"Paycom:{settings.PAYME_KEY}".encode()).decode()
        assert payme.verify_auth(f"Basic {token}") is True

    def test_wrong_login_rejected(self) -> None:
        token = base64.b64encode(f"Merchant:{settings.PAYME_KEY}".encode()).decode()
        assert payme.verify_auth(f"Basic {token}") is False

    def test_missing_header_rejected(self) -> None:
        assert payme.verify_auth(None) is False
        assert payme.verify_auth("Bearer abc") is False

    def test_garbage_header_rejected(self) -> None:
        assert payme.verify_auth("Basic !!!not-base64!!!") is False


class TestPaymeTransactions:
    async def test_check_perform_allows_a_fresh_order(self, db) -> None:
        payment = await _payment(db, PaymentProvider.PAYME)
        result = await payme.check_perform_transaction(
            db,
            {"account": {"order_id": str(payment.id)}, "amount": payment.amount_minor},
        )
        assert result == {"allow": True}

    async def test_amount_in_tiyin_is_enforced(self, db) -> None:
        payment = await _payment(db, PaymentProvider.PAYME, amount=50_000)
        assert payment.amount_minor == 5_000_000

        with pytest.raises(payme.PaymeError) as excinfo:
            await payme.check_perform_transaction(
                db, {"account": {"order_id": str(payment.id)}, "amount": 50_000}
            )
        assert excinfo.value.code == payme.ERR_INVALID_AMOUNT

    async def test_create_then_perform(self, db) -> None:
        payment = await _payment(db, PaymentProvider.PAYME)
        params = {
            "id": "payme-txn-1",
            "time": int(time.time() * 1000),
            "amount": payment.amount_minor,
            "account": {"order_id": str(payment.id)},
        }
        created = await payme.create_transaction(db, params)
        await db.commit()
        assert created["state"] == payme.STATE_CREATED

        performed = await payme.perform_transaction(db, {"id": "payme-txn-1"})
        await db.commit()
        assert performed["state"] == payme.STATE_COMPLETED

        await db.refresh(payment)
        assert payment.status == PaymentStatus.PAID

    async def test_create_is_idempotent_for_the_same_transaction(self, db) -> None:
        payment = await _payment(db, PaymentProvider.PAYME)
        params = {
            "id": "payme-txn-2",
            "time": int(time.time() * 1000),
            "amount": payment.amount_minor,
            "account": {"order_id": str(payment.id)},
        }
        first = await payme.create_transaction(db, params)
        await db.commit()
        second = await payme.create_transaction(db, params)
        await db.commit()
        assert first["transaction"] == second["transaction"]
        assert second["state"] == payme.STATE_CREATED

    async def test_second_transaction_on_a_busy_order_is_refused(self, db) -> None:
        payment = await _payment(db, PaymentProvider.PAYME)
        base = {
            "time": int(time.time() * 1000),
            "amount": payment.amount_minor,
            "account": {"order_id": str(payment.id)},
        }
        await payme.create_transaction(db, {**base, "id": "txn-a"})
        await db.commit()

        with pytest.raises(payme.PaymeError) as excinfo:
            await payme.create_transaction(db, {**base, "id": "txn-b"})
        assert excinfo.value.code == payme.ERR_CANNOT_PERFORM

    async def test_perform_is_idempotent(self, db) -> None:
        payment = await _payment(db, PaymentProvider.PAYME)
        params = {
            "id": "payme-txn-3",
            "time": int(time.time() * 1000),
            "amount": payment.amount_minor,
            "account": {"order_id": str(payment.id)},
        }
        await payme.create_transaction(db, params)
        await db.commit()
        first = await payme.perform_transaction(db, {"id": "payme-txn-3"})
        await db.commit()
        second = await payme.perform_transaction(db, {"id": "payme-txn-3"})
        await db.commit()
        assert first["perform_time"] == second["perform_time"]

    async def test_cancel_after_perform_is_state_minus_two(self, db) -> None:
        payment = await _payment(db, PaymentProvider.PAYME)
        params = {
            "id": "payme-txn-4",
            "time": int(time.time() * 1000),
            "amount": payment.amount_minor,
            "account": {"order_id": str(payment.id)},
        }
        await payme.create_transaction(db, params)
        await db.commit()
        await payme.perform_transaction(db, {"id": "payme-txn-4"})
        await db.commit()

        cancelled = await payme.cancel_transaction(db, {"id": "payme-txn-4", "reason": 5})
        await db.commit()
        assert cancelled["state"] == payme.STATE_CANCELLED_AFTER_COMPLETE

        await db.refresh(payment)
        assert payment.status == PaymentStatus.REFUNDED

    async def test_cancel_before_perform_is_state_minus_one(self, db) -> None:
        payment = await _payment(db, PaymentProvider.PAYME)
        params = {
            "id": "payme-txn-5",
            "time": int(time.time() * 1000),
            "amount": payment.amount_minor,
            "account": {"order_id": str(payment.id)},
        }
        await payme.create_transaction(db, params)
        await db.commit()

        cancelled = await payme.cancel_transaction(db, {"id": "payme-txn-5", "reason": 3})
        await db.commit()
        assert cancelled["state"] == payme.STATE_CANCELLED

    async def test_unknown_transaction_reports_the_right_code(self, db) -> None:
        with pytest.raises(payme.PaymeError) as excinfo:
            await payme.check_transaction(db, {"id": "does-not-exist"})
        assert excinfo.value.code == payme.ERR_TRANSACTION_NOT_FOUND

    async def test_unknown_order_reports_the_right_code(self, db) -> None:
        with pytest.raises(payme.PaymeError) as excinfo:
            await payme.check_perform_transaction(
                db, {"account": {"order_id": "not-a-uuid"}, "amount": 100}
            )
        assert excinfo.value.code == payme.ERR_ORDER_NOT_FOUND

    def test_error_response_carries_three_locales(self) -> None:
        error = payme.PaymeError(payme.ERR_INVALID_AMOUNT, "Invalid amount")
        response = error.to_response("req-1")
        assert set(response["error"]["message"]) == {"uz", "ru", "en"}


class TestCheckoutUrls:
    async def test_payme_checkout_encodes_the_order(self, db) -> None:
        payment = await _payment(db, PaymentProvider.PAYME)
        url = payme.checkout_url(payment)
        encoded = url.rsplit("/", 1)[1]
        decoded = base64.b64decode(encoded).decode()
        assert f"ac.order_id={payment.id}" in decoded
        assert f"a={payment.amount_minor}" in decoded

    async def test_click_checkout_contains_the_transaction_param(self, db) -> None:
        payment = await _payment(db, PaymentProvider.CLICK)
        url = click.checkout_url(payment)
        assert f"transaction_param={payment.id}" in url


class TestWebhookEndpoints:
    async def test_payme_endpoint_rejects_bad_auth(self, client) -> None:
        response = await client.post(
            "/api/v1/webhooks/payme",
            json={"jsonrpc": "2.0", "id": 1, "method": "CheckPerformTransaction"},
            headers={"Authorization": "Basic bm9wZTpub3Bl"},
        )
        assert response.status_code == 200
        assert response.json()["error"]["code"] == payme.ERR_INSUFFICIENT_PRIVILEGE

    async def test_payme_endpoint_never_returns_500(self, client) -> None:
        token = base64.b64encode(f"Paycom:{settings.PAYME_KEY}".encode()).decode()
        response = await client.post(
            "/api/v1/webhooks/payme",
            json={"jsonrpc": "2.0", "id": 1, "method": "NoSuchMethod", "params": {}},
            headers={"Authorization": f"Basic {token}"},
        )
        assert response.status_code == 200
        assert response.json()["error"]["code"] == payme.ERR_METHOD_NOT_FOUND

    async def test_click_endpoint_returns_protocol_error_not_500(self, client) -> None:
        response = await client.post("/api/v1/webhooks/click/prepare", data={})
        assert response.status_code == 200
        assert response.json()["error"] in (
            click.ERR_SIGN_CHECK_FAILED,
            click.ERR_ERROR_IN_REQUEST,
            click.ERR_USER_NOT_FOUND,
        )


class TestSignatureShape:
    def test_prepare_and_complete_sign_different_field_sets(self) -> None:
        """Complete includes merchant_prepare_id; Prepare must not."""
        import uuid as _uuid

        fake_id = _uuid.uuid4()

        class _Fake:
            id = fake_id
            amount_uzs = 50_000

        prepare = click.ClickRequest(
            click_trans_id="1",
            service_id="svc",
            click_paydoc_id=None,
            merchant_trans_id=str(fake_id),
            merchant_prepare_id=None,
            amount="50000",
            action=0,
            error=0,
            error_note=None,
            sign_time="t",
            sign_string="",
        )
        complete = click.ClickRequest(
            click_trans_id="1",
            service_id="svc",
            click_paydoc_id=None,
            merchant_trans_id=str(fake_id),
            merchant_prepare_id=str(fake_id),
            amount="50000",
            action=1,
            error=0,
            error_note=None,
            sign_time="t",
            sign_string="",
        )
        assert click.build_signature(prepare) != click.build_signature(complete)

    def test_signature_is_md5_of_the_documented_order(self) -> None:
        request = click.ClickRequest(
            click_trans_id="111",
            service_id="222",
            click_paydoc_id=None,
            merchant_trans_id="333",
            merchant_prepare_id=None,
            amount="1000",
            action=0,
            error=0,
            error_note=None,
            sign_time="2026-01-01 00:00:00",
            sign_string="",
        )
        expected = hashlib.md5(  # noqa: S324 - mirrors the Click spec
            f"111222{settings.CLICK_SECRET_KEY}3331000 0 2026-01-01 00:00:00".replace(
                " 0 ", "0"
            ).encode()
        ).hexdigest()
        assert click.build_signature(request) == expected
