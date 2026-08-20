"""Patient profile and document upload endpoints (spec 5.1, 5.2 tab 4)."""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from fastapi import APIRouter, UploadFile, status
from pydantic import BaseModel, Field

from app.api.deps import CurrentUser, DbSession, PatientUser
from app.core.errors import ConflictError, NotFoundError
from app.models.care import Document
from app.models.enums import DocumentPurpose
from app.models.profile import PatientProfile
from app.schemas.care import DocumentResponse
from app.schemas.common import ORMModel
from app.services import storage
from app.services.access import get_or_create_personal_thread

router = APIRouter(prefix="/patients", tags=["patients"])


class PatientRegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=160)
    birth_date: date | None = None
    gender: str | None = Field(default=None, max_length=16)
    region: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=4000)


class PatientProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    birth_date: date | None = None
    gender: str | None = Field(default=None, max_length=16)
    region: str | None = Field(default=None, max_length=64)
    notes: str | None = Field(default=None, max_length=4000)


class PatientProfileResponse(ORMModel):
    id: object
    user_id: object
    full_name: str
    birth_date: date | None
    gender: str | None
    region: str | None
    notes: str | None


@router.post(
    "/register", response_model=PatientProfileResponse, status_code=status.HTTP_201_CREATED
)
async def register_patient(
    payload: PatientRegisterRequest, db: DbSession, user: PatientUser
) -> PatientProfileResponse:
    """Self-registration ("Mustaqil ro'yxatdan o'taman").

    Creates the personal container immediately so anything the patient records
    before they meet a doctor has somewhere isolated to live (spec 2.2).
    """
    existing = await db.scalar(sa.select(PatientProfile).where(PatientProfile.user_id == user.id))
    if existing is not None:
        raise ConflictError("patient profile already exists", code="profile_exists")

    profile = PatientProfile(
        user_id=user.id,
        full_name=payload.full_name.strip(),
        birth_date=payload.birth_date,
        gender=payload.gender,
        region=payload.region,
        notes=payload.notes,
    )
    db.add(profile)
    if not user.full_name:
        user.full_name = profile.full_name
    if payload.birth_date and not user.birth_date:
        user.birth_date = payload.birth_date

    await get_or_create_personal_thread(db, user)
    await db.commit()
    await db.refresh(profile)
    return PatientProfileResponse.model_validate(profile)


@router.get("/me", response_model=PatientProfileResponse)
async def get_my_profile(db: DbSession, user: PatientUser) -> PatientProfileResponse:
    profile = await db.scalar(sa.select(PatientProfile).where(PatientProfile.user_id == user.id))
    if profile is None:
        raise NotFoundError("patient profile not found", code="profile_not_found")
    return PatientProfileResponse.model_validate(profile)


@router.patch("/me", response_model=PatientProfileResponse)
async def update_my_profile(
    payload: PatientProfileUpdate, db: DbSession, user: PatientUser
) -> PatientProfileResponse:
    profile = await db.scalar(sa.select(PatientProfile).where(PatientProfile.user_id == user.id))
    if profile is None:
        raise NotFoundError("patient profile not found", code="profile_not_found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)
    await db.commit()
    await db.refresh(profile)
    return PatientProfileResponse.model_validate(profile)


# ------------------------------------------------------------------- documents
documents_router = APIRouter(prefix="/documents", tags=["documents"])


@documents_router.post("", response_model=DocumentResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile,
    db: DbSession,
    user: CurrentUser,
    purpose: str = DocumentPurpose.CARE_THREAD.value,
) -> DocumentResponse:
    """Standalone upload, used before the owning record exists.

    The doctor's licence upload and the attachments on the "Mijoz qo'shish" form
    both need a document id before there is anything to attach it to.
    """
    content = await file.read()
    content_type = file.content_type or "application/octet-stream"
    storage.validate_upload(content_type, len(content))

    resolved_purpose = (
        purpose
        if purpose in {p.value for p in DocumentPurpose}
        else DocumentPurpose.CARE_THREAD.value
    )
    key = storage.build_key(resolved_purpose, user.id, file.filename or "file", content_type)
    stored = await storage.upload(content, key, content_type)

    document = Document(
        owner_user_id=user.id,
        purpose=resolved_purpose,
        storage_key=stored.key,
        filename=(file.filename or "file")[:255],
        content_type=content_type,
        size_bytes=stored.size,
        checksum=stored.checksum,
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)

    response = DocumentResponse.model_validate(document)
    response.download_url = await storage.presigned_url(
        document.storage_key, filename=document.filename
    )
    return response
