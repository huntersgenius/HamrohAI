"""Provider callbacks: Click, Payme and the IVR voice flow.

These endpoints are unauthenticated by design — each provider authenticates
itself in-band (Click: MD5 signature, Payme: HTTP Basic, Twilio: opaque call id
bound to a stored row). They must never raise: a 500 makes a provider retry
forever, so failures are converted into the provider's own error vocabulary.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from fastapi import APIRouter, Header, Request, Response

from app.api.deps import DbSession
from app.core.logging import get_logger
from app.models.care import Medication, MedicationDose, ReminderCall
from app.models.enums import DoseConfirmationChannel
from app.models.user import User
from app.services import ivr
from app.services.medications import mark_dose
from app.services.payments import click, payme

log = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ---------------------------------------------------------------------- Click
@router.post("/click/prepare")
async def click_prepare(request: Request, db: DbSession) -> dict:
    form = dict(await request.form())
    try:
        parsed = click.ClickRequest.from_form(form)
        result = await click.handle_prepare(db, parsed)
        await db.commit()
        return result
    except Exception as exc:  # noqa: BLE001 - never 500 at a payment gateway
        await db.rollback()
        log.error("webhook.click_prepare_failed", error=str(exc))
        return {"error": click.ERR_ERROR_IN_REQUEST, "error_note": "Internal error"}


@router.post("/click/complete")
async def click_complete(request: Request, db: DbSession) -> dict:
    form = dict(await request.form())
    try:
        parsed = click.ClickRequest.from_form(form)
        result = await click.handle_complete(db, parsed)
        await db.commit()
        return result
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        log.error("webhook.click_complete_failed", error=str(exc))
        return {"error": click.ERR_ERROR_IN_REQUEST, "error_note": "Internal error"}


# ---------------------------------------------------------------------- Payme
@router.post("/payme")
async def payme_endpoint(
    request: Request,
    db: DbSession,
    authorization: str = Header(default=""),
) -> dict:
    """Single JSON-RPC endpoint for every Payme merchant method."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - malformed body is a protocol error
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": payme.ERR_PARSE, "message": "Parse error"},
        }

    request_id = body.get("id")
    if not payme.verify_auth(authorization):
        log.warning("webhook.payme_unauthorized")
        return payme.PaymeError(
            payme.ERR_INSUFFICIENT_PRIVILEGE, "Insufficient privilege"
        ).to_response(request_id)

    context = payme.PaymeContext(
        method=body.get("method", ""),
        params=body.get("params") or {},
        request_id=request_id,
    )
    try:
        result = await payme.dispatch(db, context)
        await db.commit()
        return result
    except payme.PaymeError as exc:
        await db.rollback()
        return exc.to_response(request_id)
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        log.error("webhook.payme_failed", method=context.method, error=str(exc))
        return payme.PaymeError(payme.ERR_INTERNAL, "Internal error").to_response(request_id)


# ------------------------------------------------------------------------ IVR
@router.post("/ivr/{call_id}/voice")
async def ivr_voice(call_id: uuid.UUID, db: DbSession) -> Response:
    """TwiML served when the patient picks up."""
    call = await db.get(ReminderCall, call_id)
    if call is None:
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>',
            media_type="application/xml",
        )

    row = (
        await db.execute(
            sa.select(Medication)
            .join(MedicationDose, MedicationDose.medication_id == Medication.id)
            .where(MedicationDose.id == call.dose_id)
        )
    ).scalar_one_or_none()
    user = await db.get(User, call.user_id)
    medication_name = row.name if row else "dori"
    locale = user.locale if user else "uz"

    return Response(
        content=ivr.build_twiml(call.id, medication_name, locale),
        media_type="application/xml",
    )


@router.post("/ivr/{call_id}/gather")
async def ivr_gather(call_id: uuid.UUID, request: Request, db: DbSession) -> Response:
    """Record the DTMF response; pressing 1 confirms the dose."""
    form = dict(await request.form())
    digits = str(form.get("Digits", "")).strip()

    call = await db.get(ReminderCall, call_id)
    if call is None:
        return Response(
            content='<?xml version="1.0" encoding="UTF-8"?><Response><Hangup/></Response>',
            media_type="application/xml",
        )

    user = await db.get(User, call.user_id)
    locale = user.locale if user else "uz"
    confirmed = digits == "1"

    call.digits = digits[:8]
    call.status = "confirmed" if confirmed else "no_answer"

    if confirmed:
        dose = await db.get(MedicationDose, call.dose_id)
        if dose is not None:
            await mark_dose(db, dose, taken=True, channel=DoseConfirmationChannel.IVR)
    await db.commit()

    return Response(
        content=ivr.build_gather_response(confirmed, locale), media_type="application/xml"
    )


@router.post("/ivr/{call_id}/status")
async def ivr_status(call_id: uuid.UUID, request: Request, db: DbSession) -> dict:
    """Final call disposition from the provider."""
    from datetime import UTC, datetime

    form = dict(await request.form())
    call = await db.get(ReminderCall, call_id)
    if call is None:
        return {"ok": True}

    call.completed_at = datetime.now(UTC)
    # A confirmed call keeps its status; only unfinished ones take the provider's.
    if call.status != "confirmed":
        provider_status = str(form.get("CallStatus", "")).lower()
        call.status = "no_answer" if provider_status in {"no-answer", "busy"} else "placed"
    await db.commit()
    return {"ok": True}
