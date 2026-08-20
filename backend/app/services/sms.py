"""SMS delivery. Uzbek providers (Eskiz, Play Mobile) plus a mock provider."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

import httpx

from app.core.config import settings
from app.core.errors import ExternalServiceError
from app.core.logging import get_logger

log = get_logger(__name__)


class SmsProvider(ABC):
    @abstractmethod
    async def send(self, phone: str, text: str) -> str:
        """Send ``text`` to ``phone`` (E.164) and return a provider message id."""


class MockSmsProvider(SmsProvider):
    """``SMS_MODE=mock`` — nothing leaves the process.

    The message is pushed onto the mock outbox so a developer or an end-to-end
    test can read the OTP code back out (``GET /api/v1/mock/outbox?kind=sms``)
    exactly as if the SMS had arrived on the handset.
    """

    async def send(self, phone: str, text: str) -> str:
        from app.services.mocks import outbox

        event = outbox.record("sms", phone, text, sender=settings.SMS_SENDER, length=len(text))
        if settings.DEBUG:
            print(f"[SMS mock] {phone}: {text}")  # noqa: T201
        return f"mock-sms-{event.seq}"


class EskizSmsProvider(SmsProvider):
    """notify.eskiz.uz — token auth, refreshed on 401."""

    def __init__(self) -> None:
        self._token: str | None = None

    async def _login(self, client: httpx.AsyncClient) -> str:
        resp = await client.post(
            f"{settings.ESKIZ_BASE_URL}/auth/login",
            data={"email": settings.ESKIZ_EMAIL, "password": settings.ESKIZ_PASSWORD},
            timeout=15,
        )
        if resp.status_code >= 400:
            raise ExternalServiceError("eskiz auth failed", code="sms_auth_failed")
        token = resp.json().get("data", {}).get("token")
        if not token:
            raise ExternalServiceError("eskiz auth returned no token", code="sms_auth_failed")
        self._token = token
        return token

    async def send(self, phone: str, text: str) -> str:
        async with httpx.AsyncClient() as client:
            token = self._token or await self._login(client)
            payload = {
                # Eskiz expects the national number without the leading '+'.
                "mobile_phone": phone.lstrip("+"),
                "message": text,
                "from": settings.SMS_SENDER,
            }
            resp = await client.post(
                f"{settings.ESKIZ_BASE_URL}/message/sms/send",
                data=payload,
                headers={"Authorization": f"Bearer {token}"},
                timeout=20,
            )
            if resp.status_code == 401:
                token = await self._login(client)
                resp = await client.post(
                    f"{settings.ESKIZ_BASE_URL}/message/sms/send",
                    data=payload,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=20,
                )
            if resp.status_code >= 400:
                log.error("sms.eskiz_failed", status=resp.status_code)
                raise ExternalServiceError("sms delivery failed", code="sms_failed")
            return str(resp.json().get("id", ""))


class PlayMobileSmsProvider(SmsProvider):
    """send.smsxabar.uz broker API — HTTP basic auth, JSON body."""

    async def send(self, phone: str, text: str) -> str:
        message_id = f"hamroh-{int(time.time() * 1000)}"
        body = {
            "messages": [
                {
                    "recipient": phone.lstrip("+"),
                    "message-id": message_id,
                    "sms": {"originator": settings.SMS_SENDER, "content": {"text": text}},
                }
            ]
        }
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.PLAYMOBILE_BASE_URL}/send",
                json=body,
                auth=(settings.PLAYMOBILE_LOGIN, settings.PLAYMOBILE_PASSWORD),
                timeout=20,
            )
            if resp.status_code >= 400:
                log.error("sms.playmobile_failed", status=resp.status_code)
                raise ExternalServiceError("sms delivery failed", code="sms_failed")
        return message_id


_provider: SmsProvider | None = None


def get_sms_provider() -> SmsProvider:
    global _provider
    if _provider is None:
        from app.services.mocks import sms_is_mocked

        if sms_is_mocked():
            _provider = MockSmsProvider()
        elif settings.SMS_PROVIDER == "eskiz":
            _provider = EskizSmsProvider()
        elif settings.SMS_PROVIDER == "playmobile":
            _provider = PlayMobileSmsProvider()
        else:
            _provider = MockSmsProvider()
    return _provider


def set_sms_provider(provider: SmsProvider | None) -> None:
    """Test seam."""
    global _provider
    _provider = provider
