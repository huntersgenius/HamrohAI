"""SMS one-time codes.

Phone verification is mandatory for every user regardless of sign-in method
(spec 2.1, 3), so this path is both the most security-sensitive and the most
abused. Protections: hashed codes, attempt cap, resend cooldown, per-phone daily
quota, and single-use consumption.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import NotFoundError, RateLimitError, ValidationError
from app.core.i18n import translate
from app.core.logging import get_logger
from app.core.security import generate_numeric_code, hash_lookup
from app.models.enums import OtpPurpose
from app.models.user import OtpChallenge
from app.services.sms import get_sms_provider

log = get_logger(__name__)


async def start_challenge(
    db: AsyncSession,
    phone: str,
    purpose: OtpPurpose,
    *,
    locale: str = "uz",
    requested_by_user_id: uuid.UUID | None = None,
    ip_address: str | None = None,
) -> tuple[OtpChallenge, str]:
    """Create and send a fresh OTP. Returns the challenge and the plain code.

    The plain code is returned so the caller can echo it in non-production
    debugging; it is never persisted.
    """
    now = datetime.now(UTC)

    last = await db.scalar(
        sa.select(OtpChallenge)
        .where(OtpChallenge.phone == phone, OtpChallenge.purpose == purpose)
        .order_by(OtpChallenge.created_at.desc())
        .limit(1)
    )
    if last is not None:
        elapsed = (now - _aware(last.created_at)).total_seconds()
        if elapsed < settings.OTP_RESEND_COOLDOWN_SECONDS:
            raise RateLimitError(
                "please wait before requesting a new code",
                code="otp_cooldown",
                details={"retry_after": int(settings.OTP_RESEND_COOLDOWN_SECONDS - elapsed)},
            )

    day_ago = now - timedelta(days=1)
    sent_today = await db.scalar(
        sa.select(sa.func.count())
        .select_from(OtpChallenge)
        .where(OtpChallenge.phone == phone, OtpChallenge.created_at >= day_ago)
    )
    if (sent_today or 0) >= settings.OTP_MAX_PER_PHONE_PER_DAY:
        raise RateLimitError("daily SMS limit reached", code="otp_daily_limit")

    # Any earlier live challenge for this phone+purpose is invalidated, so only
    # the newest code can ever be redeemed.
    await db.execute(
        sa.update(OtpChallenge)
        .where(
            OtpChallenge.phone == phone,
            OtpChallenge.purpose == purpose,
            OtpChallenge.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )

    code = generate_numeric_code()
    challenge = OtpChallenge(
        phone=phone,
        code_hash=hash_lookup(code),
        purpose=purpose,
        expires_at=now + timedelta(seconds=settings.OTP_TTL_SECONDS),
        requested_by_user_id=requested_by_user_id,
        ip_address=ip_address,
    )
    db.add(challenge)
    await db.flush()

    text = translate("sms.otp", locale, code=code)
    await get_sms_provider().send(phone, text)
    log.info("otp.sent", purpose=purpose.value, challenge_id=str(challenge.id))
    return challenge, code


async def verify_challenge(
    db: AsyncSession, challenge_id: uuid.UUID, code: str, *, purpose: OtpPurpose | None = None
) -> OtpChallenge:
    """Consume a challenge. Raises on wrong / expired / exhausted codes."""
    challenge = await db.scalar(
        sa.select(OtpChallenge).where(OtpChallenge.id == challenge_id).with_for_update()
    )
    if challenge is None:
        raise NotFoundError("verification request not found", code="otp_not_found")
    if purpose is not None and challenge.purpose != purpose:
        raise ValidationError("verification request mismatch", code="otp_purpose_mismatch")
    if challenge.consumed_at is not None:
        raise ValidationError("code already used", code="otp_used")

    now = datetime.now(UTC)
    if _aware(challenge.expires_at) < now:
        raise ValidationError("code expired", code="otp_expired")
    if challenge.attempts >= settings.OTP_MAX_ATTEMPTS:
        raise RateLimitError("too many attempts", code="otp_attempts_exceeded")

    challenge.attempts += 1
    if not _codes_match(challenge.code_hash, code):
        await db.flush()
        remaining = max(settings.OTP_MAX_ATTEMPTS - challenge.attempts, 0)
        raise ValidationError(
            "invalid code", code="otp_invalid", details={"attempts_left": remaining}
        )

    challenge.consumed_at = now
    await db.flush()
    return challenge


def _codes_match(stored_hash: str, code: str) -> bool:
    from app.core.security import constant_time_equals

    return constant_time_equals(stored_hash, hash_lookup(code.strip()))


def _aware(value: datetime) -> datetime:
    """SQLite drops tzinfo; normalise so comparisons never explode."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def resend_available_at(challenge: OtpChallenge) -> datetime:
    return _aware(challenge.created_at) + timedelta(seconds=settings.OTP_RESEND_COOLDOWN_SECONDS)
