"""Google and Telegram sign-in verification.

Neither provider is trusted for identity on its own: both only establish "this
person controls that external account". The platform identity is always the
verified phone number (spec 2.1), which is enforced one layer up in
:mod:`app.services.auth`.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from dataclasses import dataclass

import httpx
from jose import jwt

from app.core.config import settings
from app.core.errors import AuthError, ExternalServiceError
from app.core.logging import get_logger

log = get_logger(__name__)

GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


@dataclass(frozen=True, slots=True)
class OAuthProfile:
    subject: str
    email: str | None = None
    full_name: str | None = None
    avatar_url: str | None = None
    raw: dict | None = None


class _JwksCache:
    """Google's signing keys rotate slowly; cache them for an hour."""

    def __init__(self) -> None:
        self._keys: dict | None = None
        self._fetched_at: float = 0.0

    async def get(self) -> dict:
        if self._keys is not None and time.time() - self._fetched_at < 3600:
            return self._keys
        async with httpx.AsyncClient() as client:
            resp = await client.get(GOOGLE_CERTS_URL, timeout=10)
        if resp.status_code >= 400:
            raise ExternalServiceError("cannot fetch Google keys", code="google_jwks_failed")
        self._keys = resp.json()
        self._fetched_at = time.time()
        return self._keys

    def clear(self) -> None:
        self._keys = None


_jwks = _JwksCache()


async def verify_google_id_token(id_token: str) -> OAuthProfile:
    """Verify a Google ID token's signature, issuer, audience and expiry."""
    if not settings.google_client_ids:
        raise AuthError("Google sign-in is not configured", code="google_not_configured")

    jwks = await _jwks.get()
    try:
        header = jwt.get_unverified_header(id_token)
    except Exception as exc:  # noqa: BLE001 - any malformed token
        raise AuthError("invalid Google token", code="google_token_invalid") from exc

    key = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
    if key is None:
        # Key rotation: drop the cache and retry once before giving up.
        _jwks.clear()
        jwks = await _jwks.get()
        key = next((k for k in jwks.get("keys", []) if k.get("kid") == header.get("kid")), None)
    if key is None:
        raise AuthError("unknown Google signing key", code="google_token_invalid")

    try:
        claims = jwt.decode(
            id_token,
            key,
            algorithms=["RS256"],
            audience=settings.google_client_ids,
            options={"verify_at_hash": False},
        )
    except Exception as exc:  # noqa: BLE001
        raise AuthError("invalid Google token", code="google_token_invalid") from exc

    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise AuthError("invalid Google token issuer", code="google_token_invalid")
    subject = claims.get("sub")
    if not subject:
        raise AuthError("Google token has no subject", code="google_token_invalid")

    return OAuthProfile(
        subject=str(subject),
        email=claims.get("email"),
        full_name=claims.get("name"),
        avatar_url=claims.get("picture"),
        raw={k: claims.get(k) for k in ("email_verified", "locale", "given_name", "family_name")},
    )


def verify_telegram_payload(payload: dict) -> OAuthProfile:
    """Validate the Telegram login hash (HMAC-SHA256 over the data-check string)."""
    if not settings.TELEGRAM_BOT_TOKEN:
        raise AuthError("Telegram sign-in is not configured", code="telegram_not_configured")

    received_hash = payload.get("hash")
    if not received_hash:
        raise AuthError("missing Telegram hash", code="telegram_invalid")

    auth_date = payload.get("auth_date")
    try:
        auth_ts = int(auth_date)
    except (TypeError, ValueError) as exc:
        raise AuthError("invalid Telegram auth_date", code="telegram_invalid") from exc
    if time.time() - auth_ts > settings.TELEGRAM_AUTH_MAX_AGE_SECONDS:
        raise AuthError("Telegram login expired", code="telegram_expired")

    # Data-check string: all fields except `hash`, "k=v" sorted by key, "\n"-joined.
    fields = {k: v for k, v in payload.items() if k not in {"hash", "locale"} and v is not None}
    data_check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret_key = hashlib.sha256(settings.TELEGRAM_BOT_TOKEN.encode()).digest()
    expected = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, str(received_hash)):
        raise AuthError("invalid Telegram signature", code="telegram_invalid")

    telegram_id = payload.get("id")
    if telegram_id is None:
        raise AuthError("missing Telegram id", code="telegram_invalid")

    name = " ".join(
        part for part in [payload.get("first_name"), payload.get("last_name")] if part
    ).strip()
    return OAuthProfile(
        subject=str(telegram_id),
        full_name=name or payload.get("username"),
        avatar_url=payload.get("photo_url"),
        raw={"username": payload.get("username")},
    )
