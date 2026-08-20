"""Developer-facing surface of mock mode.

These endpoints exist **only when the environment is not production** — the
router is not even mounted otherwise (``app/api/v1/router.py``), and every
handler re-checks, so a configuration slip cannot expose them.

They are deliberately unauthenticated: the checkout stand-in is opened in the
system browser, which does not carry the app's bearer token, exactly like a real
gateway page. Nothing here can be reached in production, and nothing here moves
money that a real provider would not also have moved.

Two things live here:

* ``/mock/outbox`` — everything the SMS, IVR and push mocks swallowed, so an
  end-to-end test can read back the OTP code or confirm the reminder call.
* ``/mock/checkout/{payment_id}`` and ``/mock/payments/{id}/{confirm,cancel}`` —
  the stand-in for my.click.uz / checkout.paycom.uz. Confirming runs the real
  Click or Payme callback handlers, signature and all.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse

from app.api.deps import DbSession
from app.core.config import settings
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.models.billing import Payment
from app.services.mocks import MockKind, mocked_integrations, outbox
from app.services.payments import mock as payment_mock

log = get_logger(__name__)

router = APIRouter(prefix="/mock", tags=["mock"])


def _guard() -> None:
    """Second lock on the door. The first is the router not being mounted."""
    if settings.is_production:
        raise NotFoundError("not found", code="not_found")


async def _load_payment(db: DbSession, payment_id: uuid.UUID) -> Payment:
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise NotFoundError("payment not found", code="payment_not_found")
    return payment


@router.get("/status")
async def mock_status() -> dict[str, Any]:
    """Which integrations are simulated, and what to change to go real."""
    _guard()
    return {
        "env": settings.ENV,
        "mocked": mocked_integrations(),
        "env_vars": {
            "sms": f"SMS_MODE={settings.SMS_MODE}",
            "ivr": f"IVR_MODE={settings.IVR_MODE}",
            "push": f"PUSH_MODE={settings.PUSH_MODE}",
            "payments": f"PAYMENT_MODE={settings.PAYMENT_MODE}",
            "ai": f"AI_MODE={settings.AI_MODE}",
        },
        "outbox_size": len(outbox),
    }


@router.get("/outbox")
async def read_outbox(
    kind: MockKind | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Everything mock mode simulated, newest first."""
    _guard()
    events = outbox.all(kind=kind, limit=limit)
    return {"count": len(events), "items": [event.as_dict() for event in events]}


@router.delete("/outbox", status_code=204)
async def clear_outbox() -> None:
    _guard()
    outbox.clear()


@router.get("/checkout/{payment_id}", response_class=HTMLResponse)
async def mock_checkout_page(payment_id: uuid.UUID, db: DbSession) -> HTMLResponse:
    """Stand-in for the gateway's payment page.

    Kept to plain HTML with no assets so it renders inside the app's in-app
    browser and in a terminal client alike.
    """
    _guard()
    payment = await _load_payment(db, payment_id)
    provider = payment.provider.value
    body = f"""<!doctype html>
<html lang="uz"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MOCK to'lov — Hamroh</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:0;padding:24px;background:#f4f6f8;color:#12232e}}
 .card{{max-width:420px;margin:0 auto;background:#fff;border-radius:16px;padding:24px;
        box-shadow:0 2px 16px rgba(0,0,0,.08)}}
 .warn{{background:#fff4e5;border:1px solid #ffb74d;border-radius:10px;padding:12px;
        font-size:13px;line-height:1.5;margin-bottom:20px}}
 .amount{{font-size:30px;font-weight:700;margin:8px 0 20px}}
 button{{width:100%;padding:14px;border:0;border-radius:10px;font-size:16px;
         font-weight:600;margin-bottom:10px;cursor:pointer}}
 .pay{{background:#0f9d58;color:#fff}} .cancel{{background:#eceff1;color:#37474f}}
 pre{{background:#263238;color:#b2ff59;padding:12px;border-radius:10px;
      font-size:12px;overflow:auto;white-space:pre-wrap}}
</style></head><body><div class="card">
<div class="warn"><b>MOCK REJIM — bu haqiqiy to'lov emas.</b><br>
Click/Payme merchant hisobi hali ochilmagan. Bu sahifa haqiqiy shlyuz o'rniga
turadi va hech qanday pul harakati sodir bo'lmaydi. Haqiqiy shlyuzga o'tish
uchun <code>PAYMENT_MODE=real</code> qiling.</div>
<div>To'lov tizimi: <b>{provider}</b></div>
<div class="amount">{payment.amount_uzs:,} so'm</div>
<button class="pay" onclick="act('confirm')">To'lovni tasdiqlash (muvaffaqiyatli)</button>
<button class="cancel" onclick="act('cancel')">Bekor qilish (muvaffaqiyatsiz)</button>
<pre id="out">Natija shu yerda chiqadi.</pre>
</div><script>
async function act(what) {{
  const out = document.getElementById('out');
  out.textContent = 'Yuborilmoqda...';
  const r = await fetch('../payments/{payment_id}/' + what, {{method: 'POST'}});
  out.textContent = JSON.stringify(await r.json(), null, 2);
}}
</script></body></html>"""
    return HTMLResponse(body)


@router.post("/payments/{payment_id}/confirm")
async def confirm_payment(payment_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Simulate the gateway confirming the payment.

    Runs the real ``handle_prepare``/``handle_complete`` (Click) or
    ``CreateTransaction``/``PerformTransaction`` (Payme) sequence, so the
    consultation activation, the 80/20 split and the wallet credit all happen
    through production code.
    """
    _guard()
    payment = await _load_payment(db, payment_id)
    result = await payment_mock.simulate_success(db, payment)
    await db.commit()
    await db.refresh(payment)
    return {"payment_status": payment.status.value, **result}


@router.post("/payments/{payment_id}/cancel")
async def cancel_payment(payment_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Simulate the gateway reporting a failed payment."""
    _guard()
    payment = await _load_payment(db, payment_id)
    result = await payment_mock.simulate_failure(db, payment)
    await db.commit()
    await db.refresh(payment)
    return {"payment_status": payment.status.value, **result}
