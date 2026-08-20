"""Account resolution, session issuing and the phone-identity merge rule.

Spec 2.1, restated as code:

* the phone number is the only real identity key;
* whichever provider signs a user in, phone verification is mandatory and cannot
  be skipped;
* if the same phone reappears through a different provider, that provider is
  attached to the **existing** account — never a duplicate one.

Sign-in with Google/Telegram before any phone is known therefore does not issue a
session. It issues a short-lived *onboarding token* that authorises exactly one
action: verifying a phone number. Only after that does a real token pair exist.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AuthError, ConflictError, ForbiddenError
from app.core.logging import get_logger
from app.core.security import (
    create_token,
    decode_token,
    generate_refresh_token,
    hash_lookup,
)
from app.models.enums import AuthProvider, UserRole
from app.models.user import AuthIdentity, DeviceToken, RefreshSession, User
from app.schemas.auth import AuthState, TokenPair
from app.services.oauth import OAuthProfile

log = get_logger(__name__)


# ------------------------------------------------------------------ user lookup
async def get_user_by_phone(db: AsyncSession, phone: str) -> User | None:
    return await db.scalar(sa.select(User).where(User.phone == phone))


async def get_user_by_identity(
    db: AsyncSession, provider: AuthProvider, subject: str
) -> User | None:
    identity = await db.scalar(
        sa.select(AuthIdentity).where(
            AuthIdentity.provider == provider, AuthIdentity.subject == subject
        )
    )
    if identity is None:
        return None
    return await db.get(User, identity.user_id)


async def get_or_create_user_by_phone(
    db: AsyncSession, phone: str, *, locale: str = "uz"
) -> tuple[User, bool]:
    """Return ``(user, created)`` for a verified phone number."""
    user = await get_user_by_phone(db, phone)
    if user is not None:
        return user, False
    user = User(phone=phone, locale=locale, phone_verified_at=datetime.now(UTC))
    db.add(user)
    await db.flush()
    await attach_identity(db, user, AuthProvider.PHONE, phone, {})
    log.info("auth.user_created", user_id=str(user.id))
    return user, True


async def attach_identity(
    db: AsyncSession,
    user: User,
    provider: AuthProvider,
    subject: str,
    raw_profile: dict | None = None,
) -> AuthIdentity:
    """Link a login method to ``user``, or return the existing link.

    This is the merge step: signing in with Google using a phone that already has
    an account attaches Google to that account instead of creating a second one.
    """
    existing = await db.scalar(
        sa.select(AuthIdentity).where(
            AuthIdentity.provider == provider, AuthIdentity.subject == subject
        )
    )
    if existing is not None:
        if existing.user_id != user.id:
            # The same external account cannot back two platform identities.
            raise ConflictError(
                "this login is already linked to another account",
                code="identity_already_linked",
            )
        existing.last_used_at = datetime.now(UTC)
        return existing

    # One identity per provider per user: re-linking a different Google account
    # replaces the previous subject rather than accumulating stale rows.
    same_provider = await db.scalar(
        sa.select(AuthIdentity).where(
            AuthIdentity.user_id == user.id, AuthIdentity.provider == provider
        )
    )
    if same_provider is not None:
        same_provider.subject = subject
        same_provider.raw_profile = raw_profile or {}
        same_provider.last_used_at = datetime.now(UTC)
        await db.flush()
        return same_provider

    identity = AuthIdentity(
        user_id=user.id,
        provider=provider,
        subject=subject,
        raw_profile=raw_profile or {},
        last_used_at=datetime.now(UTC),
    )
    db.add(identity)
    await db.flush()
    log.info("auth.identity_linked", user_id=str(user.id), provider=provider.value)
    return identity


def apply_oauth_profile(user: User, profile: OAuthProfile) -> None:
    """Fill in blanks from the provider without overwriting user-set values."""
    if profile.full_name and not user.full_name:
        user.full_name = profile.full_name[:160]
    if profile.email and not user.email:
        user.email = profile.email[:255]
    if profile.avatar_url and not user.avatar_url:
        user.avatar_url = profile.avatar_url[:512]


# -------------------------------------------------------------- onboarding token
def issue_onboarding_token(profile: OAuthProfile, provider: AuthProvider, locale: str) -> str:
    """Token proving a verified external sign-in, pending phone verification.

    Deliberately not a session: it carries no user id and grants no API access
    beyond the phone-verification endpoint.
    """
    token, _ = create_token(
        subject=profile.subject,
        token_type="onboarding",
        extra={
            "provider": provider.value,
            "email": profile.email,
            "name": profile.full_name,
            "avatar": profile.avatar_url,
            "locale": locale,
        },
    )
    return token


def read_onboarding_token(token: str) -> tuple[AuthProvider, OAuthProfile, str]:
    payload = decode_token(token, expected_type="onboarding")
    try:
        provider = AuthProvider(payload["provider"])
    except (KeyError, ValueError) as exc:
        raise AuthError("invalid onboarding token", code="invalid_token") from exc
    profile = OAuthProfile(
        subject=str(payload.get("sub")),
        email=payload.get("email"),
        full_name=payload.get("name"),
        avatar_url=payload.get("avatar"),
    )
    return provider, profile, payload.get("locale") or "uz"


# --------------------------------------------------------------------- sessions
async def issue_tokens(
    db: AsyncSession,
    user: User,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenPair:
    """Mint an access token and a stored, rotatable refresh token."""
    if user.is_blocked or not user.is_active:
        raise ForbiddenError("account is disabled", code="account_disabled")
    if not user.is_phone_verified:
        # Belt and braces: no session may exist without a verified phone.
        raise AuthError("phone verification required", code="phone_verification_required")

    access_token, expires_at = create_token(
        user.id, "access", extra={"role": user.role.value if user.role else None}
    )
    raw_refresh = generate_refresh_token()
    session = RefreshSession(
        user_id=user.id,
        token_hash=hash_lookup(raw_refresh),
        expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS),
        user_agent=(user_agent or "")[:255] or None,
        ip_address=(ip_address or "")[:64] or None,
    )
    db.add(session)
    user.last_seen_at = datetime.now(UTC)
    await db.flush()

    return TokenPair(access_token=access_token, refresh_token=raw_refresh, expires_at=expires_at)


async def rotate_refresh_token(
    db: AsyncSession,
    raw_token: str,
    *,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenPair:
    """Exchange a refresh token for a new pair, invalidating the old one.

    Reuse of an already-rotated token is treated as theft: every session for that
    user is revoked.
    """
    token_hash = hash_lookup(raw_token)
    session = await db.scalar(
        sa.select(RefreshSession).where(RefreshSession.token_hash == token_hash)
    )
    if session is None:
        raise AuthError("invalid refresh token", code="invalid_refresh_token")

    now = datetime.now(UTC)
    if session.revoked_at is not None:
        log.warning("auth.refresh_reuse_detected", user_id=str(session.user_id))
        await db.execute(
            sa.update(RefreshSession)
            .where(RefreshSession.user_id == session.user_id, RefreshSession.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        await db.flush()
        raise AuthError("refresh token reuse detected", code="refresh_token_reused")

    if _aware(session.expires_at) < now:
        raise AuthError("refresh token expired", code="refresh_token_expired")

    user = await db.get(User, session.user_id)
    if user is None:
        raise AuthError("account not found", code="account_not_found")

    session.revoked_at = now
    tokens = await issue_tokens(db, user, user_agent=user_agent, ip_address=ip_address)
    new_session = await db.scalar(
        sa.select(RefreshSession)
        .where(RefreshSession.token_hash == hash_lookup(tokens.refresh_token))
        .limit(1)
    )
    if new_session is not None:
        session.replaced_by_id = new_session.id
    await db.flush()
    return tokens


async def revoke_session(db: AsyncSession, raw_token: str) -> None:
    session = await db.scalar(
        sa.select(RefreshSession).where(RefreshSession.token_hash == hash_lookup(raw_token))
    )
    if session is not None and session.revoked_at is None:
        session.revoked_at = datetime.now(UTC)
        await db.flush()


async def revoke_all_sessions(db: AsyncSession, user_id: uuid.UUID) -> None:
    await db.execute(
        sa.update(RefreshSession)
        .where(RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def deactivate_device(db: AsyncSession, user_id: uuid.UUID, token: str) -> None:
    await db.execute(
        sa.update(DeviceToken)
        .where(DeviceToken.user_id == user_id, DeviceToken.token == token)
        .values(is_active=False)
    )


# ------------------------------------------------------------------------ state
async def build_auth_state(db: AsyncSession, user: User) -> AuthState:
    """What the app must show next after authentication."""
    profile_setup_required = False
    if user.role == UserRole.DOCTOR:
        from app.models.profile import DoctorProfile

        exists = await db.scalar(
            sa.select(sa.func.count())
            .select_from(DoctorProfile)
            .where(DoctorProfile.user_id == user.id)
        )
        profile_setup_required = not exists
    elif user.role == UserRole.PATIENT:
        from app.models.profile import PatientProfile

        exists = await db.scalar(
            sa.select(sa.func.count())
            .select_from(PatientProfile)
            .where(PatientProfile.user_id == user.id)
        )
        profile_setup_required = not exists

    return AuthState(
        phone_verification_required=not user.is_phone_verified,
        role_selection_required=user.role is None,
        profile_setup_required=profile_setup_required,
        role=user.role,
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
