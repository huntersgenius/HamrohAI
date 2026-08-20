"""Authentication endpoints (spec 3).

The phone gate is the invariant: Google and Telegram sign-in never return a
session directly. They return an *onboarding token*, and the only thing it can
do is complete phone verification — which then resolves (or creates) the single
account that owns that number.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from app.api.deps import ClientIp, CurrentUser, DbSession, UserAgent
from app.core.config import settings
from app.core.errors import AuthError, ValidationError
from app.core.phone import normalize_phone
from app.models.enums import AuthProvider, OtpPurpose, UserRole
from app.models.user import DeviceToken, User
from app.schemas.auth import (
    AuthState,
    LogoutRequest,
    OAuthGoogleRequest,
    OAuthTelegramRequest,
    RefreshRequest,
    RegisterDeviceRequest,
    SelectRoleRequest,
    SessionResponse,
    StartPhoneAuthRequest,
    StartPhoneAuthResponse,
    TokenPair,
    UpdateMeRequest,
    UserResponse,
    VerifyPhoneRequest,
)
from app.schemas.common import OkResponse
from app.services import auth as auth_service
from app.services import oauth, otp

router = APIRouter(prefix="/auth", tags=["auth"])


def _debug_code(code: str) -> str | None:
    # Never leak a live OTP in production, whatever the flag says.
    if settings.OTP_DEBUG_RETURN_CODE and not settings.is_production:
        return code
    return None


@router.post("/phone/start", response_model=StartPhoneAuthResponse)
async def start_phone_auth(
    payload: StartPhoneAuthRequest, db: DbSession, ip: ClientIp
) -> StartPhoneAuthResponse:
    """Send an SMS code to begin (or continue) phone sign-in."""
    challenge, code = await otp.start_challenge(
        db, payload.phone, OtpPurpose.LOGIN, locale=payload.locale, ip_address=ip
    )
    await db.commit()
    return StartPhoneAuthResponse(
        challenge_id=challenge.id,
        expires_at=challenge.expires_at,
        resend_available_at=otp.resend_available_at(challenge),
        debug_code=_debug_code(code),
    )


@router.post("/phone/verify", response_model=SessionResponse)
async def verify_phone(
    payload: VerifyPhoneRequest,
    db: DbSession,
    ip: ClientIp,
    ua: UserAgent,
) -> SessionResponse:
    """Verify the code and issue a session.

    When ``onboarding_token`` is present the caller signed in with Google or
    Telegram first: that provider is attached to whichever account owns this
    phone number, creating one only if none exists (spec 2.1).
    """
    challenge = await otp.verify_challenge(db, payload.challenge_id, payload.code)

    user, created = await auth_service.get_or_create_user_by_phone(db, challenge.phone)
    if not user.is_phone_verified:
        from datetime import UTC, datetime

        user.phone_verified_at = datetime.now(UTC)

    if payload.onboarding_token:
        provider, profile, locale = auth_service.read_onboarding_token(
            payload.onboarding_token
        )
        await auth_service.attach_identity(
            db, user, provider, profile.subject, {"email": profile.email}
        )
        auth_service.apply_oauth_profile(user, profile)
        if created:
            user.locale = locale

    tokens = await auth_service.issue_tokens(db, user, user_agent=ua, ip_address=ip)
    state = await auth_service.build_auth_state(db, user)
    await db.commit()
    return SessionResponse(tokens=tokens, state=state, user=UserResponse.model_validate(user))


@router.post("/google", response_model=SessionResponse)
async def google_sign_in(
    payload: OAuthGoogleRequest, db: DbSession, ip: ClientIp, ua: UserAgent
) -> SessionResponse:
    """Google sign-in.

    Returns a full session only for an account whose phone is already verified;
    otherwise the phone-verification screen is mandatory and cannot be skipped.
    """
    profile = await oauth.verify_google_id_token(payload.id_token)
    return await _complete_oauth(db, AuthProvider.GOOGLE, profile, payload.locale, ip=ip, ua=ua)


@router.post("/telegram", response_model=SessionResponse)
async def telegram_sign_in(
    payload: OAuthTelegramRequest, db: DbSession, ip: ClientIp, ua: UserAgent
) -> SessionResponse:
    profile = oauth.verify_telegram_payload(payload.model_dump())
    return await _complete_oauth(db, AuthProvider.TELEGRAM, profile, payload.locale, ip=ip, ua=ua)


async def _complete_oauth(
    db: DbSession,
    provider: AuthProvider,
    profile: oauth.OAuthProfile,
    locale: str,
    *,
    ip: str | None,
    ua: str | None,
) -> SessionResponse:
    user = await auth_service.get_user_by_identity(db, provider, profile.subject)

    if user is not None and user.is_phone_verified:
        auth_service.apply_oauth_profile(user, profile)
        await auth_service.attach_identity(db, user, provider, profile.subject)
        tokens = await auth_service.issue_tokens(db, user, user_agent=ua, ip_address=ip)
        state = await auth_service.build_auth_state(db, user)
        await db.commit()
        return SessionResponse(tokens=tokens, state=state, user=UserResponse.model_validate(user))

    # No verified phone yet: hand back a token that only unlocks the phone step.
    await db.commit()
    return SessionResponse(
        onboarding_token=auth_service.issue_onboarding_token(profile, provider, locale),
        state=AuthState(
            phone_verification_required=True,
            role_selection_required=True,
            profile_setup_required=True,
        ),
    )


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, db: DbSession, ip: ClientIp, ua: UserAgent) -> TokenPair:
    tokens = await auth_service.rotate_refresh_token(
        db, payload.refresh_token, user_agent=ua, ip_address=ip
    )
    await db.commit()
    return tokens


@router.post("/logout", response_model=OkResponse)
async def logout(payload: LogoutRequest, db: DbSession, user: CurrentUser) -> OkResponse:
    if payload.refresh_token:
        await auth_service.revoke_session(db, payload.refresh_token)
    if payload.device_token:
        await auth_service.deactivate_device(db, user.id, payload.device_token)
    await db.commit()
    return OkResponse()


@router.post("/logout/all", response_model=OkResponse)
async def logout_all(db: DbSession, user: CurrentUser) -> OkResponse:
    await auth_service.revoke_all_sessions(db, user.id)
    await db.commit()
    return OkResponse()


@router.get("/me", response_model=UserResponse)
async def get_me(user: CurrentUser) -> UserResponse:
    return UserResponse.model_validate(user)


@router.get("/state", response_model=AuthState)
async def get_state(db: DbSession, user: CurrentUser) -> AuthState:
    return await auth_service.build_auth_state(db, user)


@router.patch("/me", response_model=UserResponse)
async def update_me(payload: UpdateMeRequest, db: DbSession, user: CurrentUser) -> UserResponse:
    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)


@router.post("/role", response_model=SessionResponse)
async def select_role(
    payload: SelectRoleRequest, db: DbSession, user: CurrentUser
) -> SessionResponse:
    """First-run role choice. Deliberately one-way (spec 3).

    A patient's clinical data and a doctor's practice are different worlds;
    flipping roles on a live account would strand records in both.
    """
    if user.role is not None:
        raise ValidationError("role has already been selected", code="role_already_set")
    user.role = UserRole(payload.role)
    await db.flush()
    state = await auth_service.build_auth_state(db, user)
    await db.commit()
    await db.refresh(user)
    return SessionResponse(state=state, user=UserResponse.model_validate(user))


@router.post("/devices", response_model=OkResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    payload: RegisterDeviceRequest, db: DbSession, user: CurrentUser
) -> OkResponse:
    """Register/refresh this installation's push token."""
    from datetime import UTC, datetime

    import sqlalchemy as sa

    existing = await db.scalar(sa.select(DeviceToken).where(DeviceToken.token == payload.token))
    if existing is not None:
        # A reinstall can hand the same token to a different account.
        existing.user_id = user.id
        existing.platform = payload.platform
        existing.locale = payload.locale
        existing.app_version = payload.app_version
        existing.is_active = True
        existing.last_used_at = datetime.now(UTC)
    else:
        db.add(
            DeviceToken(
                user_id=user.id,
                token=payload.token,
                platform=payload.platform,
                locale=payload.locale,
                app_version=payload.app_version,
                last_used_at=datetime.now(UTC),
            )
        )
    await db.commit()
    return OkResponse()


@router.post("/phone/change/start", response_model=StartPhoneAuthResponse)
async def start_phone_change(
    payload: StartPhoneAuthRequest, db: DbSession, user: CurrentUser, ip: ClientIp
) -> StartPhoneAuthResponse:
    """Begin moving this account to a different phone number."""
    import sqlalchemy as sa

    phone = normalize_phone(payload.phone)
    taken = await db.scalar(sa.select(User.id).where(User.phone == phone, User.id != user.id))
    if taken:
        raise ValidationError("this number already belongs to another account", code="phone_taken")

    challenge, code = await otp.start_challenge(
        db,
        phone,
        OtpPurpose.CHANGE_PHONE,
        locale=user.locale,
        requested_by_user_id=user.id,
        ip_address=ip,
    )
    await db.commit()
    return StartPhoneAuthResponse(
        challenge_id=challenge.id,
        expires_at=challenge.expires_at,
        resend_available_at=otp.resend_available_at(challenge),
        debug_code=_debug_code(code),
    )


@router.post("/phone/change/verify", response_model=UserResponse)
async def verify_phone_change(
    payload: VerifyPhoneRequest, db: DbSession, user: CurrentUser
) -> UserResponse:
    challenge = await otp.verify_challenge(
        db, payload.challenge_id, payload.code, purpose=OtpPurpose.CHANGE_PHONE
    )
    if challenge.requested_by_user_id != user.id:
        raise AuthError("verification request does not belong to you", code="otp_not_yours")

    user.phone = challenge.phone
    await auth_service.attach_identity(db, user, AuthProvider.PHONE, challenge.phone)
    # Changing the identity key invalidates every other session.
    await auth_service.revoke_all_sessions(db, user.id)
    await db.commit()
    await db.refresh(user)
    return UserResponse.model_validate(user)
