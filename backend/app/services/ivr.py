"""Voice-call medication reminders (spec: "Ovozli qo'ng'iroq orqali dori eslatmasi").

Flow: at the scheduled time a push goes out. If the patient has not pressed
"Ichdim" within ``IVR_DELAY_MINUTES`` (15-20), the system places an automated
call that reads a pre-recorded message and asks the patient to press 1. Pressing
1 is recorded as a confirmation of that exact dose.

Calls are only placed when the patient has left "Qo'ng'iroq orqali eslatish" on —
it defaults to on but must be switchable off.
"""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from xml.sax.saxutils import escape

import httpx

from app.core.config import settings
from app.core.i18n import translate
from app.core.logging import get_logger
from app.models.care import ReminderCall

log = get_logger(__name__)


class IvrProvider(ABC):
    @abstractmethod
    async def place_call(self, phone: str, call_id: uuid.UUID) -> str:
        """Place the call and return a provider call id."""


class ConsoleIvrProvider(IvrProvider):
    async def place_call(self, phone: str, call_id: uuid.UUID) -> str:
        log.info("ivr.console_call", to=phone[-4:], call_id=str(call_id))
        return f"console-call-{call_id.hex[:12]}"


class TwilioIvrProvider(IvrProvider):
    """Twilio Programmable Voice.

    The call is created with a webhook URL pointing back at this API; Twilio
    fetches TwiML from :func:`build_twiml` when the patient answers.
    """

    async def place_call(self, phone: str, call_id: uuid.UUID) -> str:
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.TWILIO_ACCOUNT_SID}/Calls.json"
        callback = f"{settings.IVR_WEBHOOK_BASE_URL}/api/v1/webhooks/ivr/{call_id}/voice"
        status_callback = f"{settings.IVR_WEBHOOK_BASE_URL}/api/v1/webhooks/ivr/{call_id}/status"
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                url,
                data={
                    "To": phone,
                    "From": settings.TWILIO_FROM_NUMBER,
                    "Url": callback,
                    "StatusCallback": status_callback,
                    "StatusCallbackEvent": "completed",
                    "Timeout": "25",
                },
                auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
            )
        if resp.status_code >= 400:
            log.error("ivr.twilio_failed", status=resp.status_code)
            raise RuntimeError(f"twilio call failed: {resp.status_code}")
        return str(resp.json().get("sid", ""))


_provider: IvrProvider | None = None


def get_ivr_provider() -> IvrProvider:
    global _provider
    if _provider is None:
        _provider = (
            TwilioIvrProvider() if settings.IVR_PROVIDER == "twilio" else ConsoleIvrProvider()
        )
    return _provider


def set_ivr_provider(provider: IvrProvider | None) -> None:
    """Test seam."""
    global _provider
    _provider = provider


# Twilio speaks these locales; Uzbek has no voice, so Russian is the closest
# intelligible fallback for an Uzbek speaker in this market.
_TWILIO_VOICE_LOCALE = {"uz": "ru-RU", "ru": "ru-RU", "en": "en-US"}


def build_twiml(call_id: uuid.UUID, medication_name: str, locale: str) -> str:
    """TwiML read to the patient, asking them to press 1."""
    text = translate("ivr.medication_reminder", locale, medication=medication_name)
    action = f"{settings.IVR_WEBHOOK_BASE_URL}/api/v1/webhooks/ivr/{call_id}/gather"
    voice_locale = _TWILIO_VOICE_LOCALE.get(locale, "ru-RU")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Gather numDigits="1" action="{escape(action)}" method="POST" timeout="8">'
        f'<Say language="{voice_locale}">{escape(text)}</Say>'
        f'<Say language="{voice_locale}">{escape(text)}</Say>'
        "</Gather>"
        f'<Say language="{voice_locale}">{escape(translate("ivr.not_confirmed", locale))}</Say>'
        "</Response>"
    )


def build_gather_response(confirmed: bool, locale: str) -> str:
    key = "ivr.confirmed" if confirmed else "ivr.not_confirmed"
    voice_locale = _TWILIO_VOICE_LOCALE.get(locale, "ru-RU")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Say language="{voice_locale}">{escape(translate(key, locale))}</Say>'
        "<Hangup/>"
        "</Response>"
    )


async def place_reminder_call(call: ReminderCall) -> None:
    """Dispatch one scheduled call, recording the outcome on the row."""
    try:
        provider_id = await get_ivr_provider().place_call(call.phone, call.id)
    except Exception as exc:  # noqa: BLE001 - a failed call must not break the batch
        call.status = "failed"
        call.error = str(exc)[:500]
        log.error("ivr.place_failed", call_id=str(call.id), error=str(exc))
        return
    call.provider_call_id = provider_id
    call.status = "placed"
    call.placed_at = datetime.now(UTC)
