"""FastAPI dependencies: authentication, role gates, pagination."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AuthError, ForbiddenError
from app.core.security import decode_token
from app.models.enums import DoctorVerificationStatus, UserRole
from app.models.profile import DoctorProfile, PatientProfile
from app.models.user import User
from app.schemas.common import PageParams

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if credentials is None or not credentials.credentials:
        raise AuthError("authentication required", code="not_authenticated")

    payload = decode_token(credentials.credentials, expected_type="access")
    import uuid as _uuid

    try:
        user_id = _uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise AuthError("invalid token subject", code="invalid_token") from exc

    user = await db.get(User, user_id)
    if user is None:
        raise AuthError("account not found", code="account_not_found")
    if user.is_blocked or not user.is_active:
        raise ForbiddenError("account is disabled", code="account_disabled")
    # Belt and braces: every authenticated request re-checks the phone gate
    # (spec 2.1), so a token minted before a policy change cannot slip through.
    if not user.is_phone_verified:
        raise AuthError("phone verification required", code="phone_verification_required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_doctor(db: DbSession, user: CurrentUser) -> User:
    if user.role != UserRole.DOCTOR:
        raise ForbiddenError("doctor role required", code="doctor_role_required")
    return user


DoctorUser = Annotated[User, Depends(get_current_doctor)]


async def get_verified_doctor(db: DbSession, user: DoctorUser) -> User:
    """A doctor whose licence has been approved.

    Approval is granted manually in the database in the MVP — there is no
    in-app approval screen (spec 1).
    """
    import sqlalchemy as sa

    profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
    if profile is None:
        raise ForbiddenError("doctor profile required", code="doctor_profile_required")
    if profile.verification_status != DoctorVerificationStatus.APPROVED:
        raise ForbiddenError(
            "your profile is awaiting verification",
            code="doctor_not_verified",
            details={"status": profile.verification_status.value},
        )
    return user


VerifiedDoctor = Annotated[User, Depends(get_verified_doctor)]


async def get_subscribed_doctor(db: DbSession, user: VerifiedDoctor) -> User:
    """A verified doctor with an active subscription (spec 7)."""
    from app.services.billing import require_active_subscription

    await require_active_subscription(db, user)
    return user


SubscribedDoctor = Annotated[User, Depends(get_subscribed_doctor)]


async def get_current_patient(db: DbSession, user: CurrentUser) -> User:
    if user.role != UserRole.PATIENT:
        raise ForbiddenError("patient role required", code="patient_role_required")
    return user


PatientUser = Annotated[User, Depends(get_current_patient)]


async def get_doctor_profile(db: DbSession, user: DoctorUser) -> DoctorProfile:
    import sqlalchemy as sa

    profile = await db.scalar(sa.select(DoctorProfile).where(DoctorProfile.user_id == user.id))
    if profile is None:
        raise ForbiddenError("doctor profile required", code="doctor_profile_required")
    return profile


async def get_patient_profile(db: DbSession, user: PatientUser) -> PatientProfile:
    import sqlalchemy as sa

    profile = await db.scalar(sa.select(PatientProfile).where(PatientProfile.user_id == user.id))
    if profile is None:
        raise ForbiddenError("patient profile required", code="patient_profile_required")
    return profile


def get_page_params(limit: int = 20, offset: int = 0) -> PageParams:
    return PageParams(limit=limit, offset=offset)


Pagination = Annotated[PageParams, Depends(get_page_params)]


def client_ip(request: Request) -> str | None:
    """Real client IP behind the reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


ClientIp = Annotated[str | None, Depends(client_ip)]


def user_agent(user_agent: Annotated[str | None, Header(alias="user-agent")] = None) -> str | None:
    return user_agent


UserAgent = Annotated[str | None, Depends(user_agent)]
