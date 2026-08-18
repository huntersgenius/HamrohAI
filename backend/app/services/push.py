"""Push delivery via Firebase Cloud Messaging (HTTP v1)."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import httpx
from jose import jwt

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass(slots=True)
class PushResult:
    delivered: int = 0
    failed: int = 0
    invalid_tokens: list[str] = field(default_factory=list)
    error: str | None = None


class _AccessTokenCache:
    """Service-account access tokens live an hour; mint one and reuse it."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._expires_at: float = 0.0

    async def get(self) -> str:
        if self._token and time.time() < self._expires_at - 60:
            return self._token

        credentials = json.loads(settings.FCM_CREDENTIALS_JSON)
        now = int(time.time())
        assertion = jwt.encode(
            {
                "iss": credentials["client_email"],
                "scope": FCM_SCOPE,
                "aud": GOOGLE_TOKEN_URL,
                "iat": now,
                "exp": now + 3600,
            },
            credentials["private_key"],
            algorithm="RS256",
        )
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
                timeout=15,
            )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._expires_at = time.time() + int(body.get("expires_in", 3600))
        return self._token


_token_cache = _AccessTokenCache()


async def send_push(
    tokens: list[str], *, title: str, body: str, data: dict[str, str] | None = None
) -> PushResult:
    """Send one notification to many device tokens."""
    if not tokens:
        return PushResult()

    if settings.PUSH_PROVIDER != "fcm" or not settings.FCM_CREDENTIALS_JSON:
        log.info("push.console", count=len(tokens), title=title)
        return PushResult(delivered=len(tokens))

    result = PushResult()
    try:
        access_token = await _token_cache.get()
    except Exception as exc:  # noqa: BLE001 - credentials/network, both non-fatal
        log.error("push.auth_failed", error=str(exc))
        return PushResult(failed=len(tokens), error="fcm_auth_failed")

    url = f"https://fcm.googleapis.com/v1/projects/{settings.FCM_PROJECT_ID}/messages:send"
    headers = {"Authorization": f"Bearer {access_token}"}

    async with httpx.AsyncClient(timeout=20) as client:
        for token in tokens:
            payload = {
                "message": {
                    "token": token,
                    "notification": {"title": title, "body": body},
                    "data": data or {},
                    "android": {"priority": "high"},
                    "apns": {
                        "headers": {"apns-priority": "10"},
                        "payload": {"aps": {"sound": "default"}},
                    },
                }
            }
            try:
                resp = await client.post(url, json=payload, headers=headers)
            except httpx.HTTPError as exc:
                result.failed += 1
                result.error = str(exc)[:200]
                continue

            if resp.status_code < 300:
                result.delivered += 1
                continue

            result.failed += 1
            # 404 UNREGISTERED / 400 INVALID_ARGUMENT mean the token is dead.
            if resp.status_code in (400, 404):
                result.invalid_tokens.append(token)
            else:
                result.error = f"fcm_{resp.status_code}"

    return result
