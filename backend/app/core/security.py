"""Token issuing/verification, hashing and short-code generation."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings
from app.core.errors import AuthError

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

TokenType = Literal["access", "refresh", "onboarding"]

# Codes avoid look-alike characters (0/O, 1/I/L) so they survive being read out
# over the phone or copied from an SMS.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def hash_secret(raw: str) -> str:
    return _pwd.hash(raw)


def verify_secret(raw: str, hashed: str) -> bool:
    try:
        return _pwd.verify(raw, hashed)
    except ValueError:
        return False


def hash_lookup(raw: str) -> str:
    """Deterministic keyed hash, for values we must look up but never store raw.

    Used for OTP codes and refresh tokens: a database leak must not hand the
    attacker usable credentials, but we still need an equality lookup.
    """
    return hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()


def generate_numeric_code(length: int | None = None) -> str:
    length = length or settings.OTP_LENGTH
    return "".join(secrets.choice(string.digits) for _ in range(length))


def generate_short_code(length: int = 8) -> str:
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def create_token(
    subject: str | uuid.UUID,
    token_type: TokenType,
    *,
    expires_delta: timedelta | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    if expires_delta is None:
        if token_type == "access":
            expires_delta = timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)
        elif token_type == "refresh":
            expires_delta = timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)
        else:  # onboarding tokens are short lived by design
            expires_delta = timedelta(minutes=30)
    expires_at = now + expires_delta
    payload: dict[str, Any] = {
        "sub": str(subject),
        "typ": token_type,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": uuid.uuid4().hex,
    }
    if extra:
        payload.update(extra)
    token = jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return token, expires_at


def decode_token(token: str, expected_type: TokenType | None = None) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise AuthError("invalid or expired token", code="invalid_token") from exc
    if expected_type and payload.get("typ") != expected_type:
        raise AuthError("unexpected token type", code="invalid_token")
    return payload


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
