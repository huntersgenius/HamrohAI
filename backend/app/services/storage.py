"""S3-compatible object storage (MinIO) for medical documents.

Buckets live on infrastructure inside Uzbekistan — a legal requirement for
medical data, not a performance choice (spec 1). Files are never public: reads
go through short-lived presigned URLs issued only to a caller the API has
already authorised for that care thread.
"""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from dataclasses import dataclass

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import settings
from app.core.errors import ExternalServiceError, ValidationError
from app.core.logging import get_logger

log = get_logger(__name__)

ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "application/pdf",
}

_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "application/pdf": ".pdf",
}


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    size: int
    content_type: str
    checksum: str


def _session() -> aioboto3.Session:
    return aioboto3.Session()


def _client_kwargs() -> dict:
    return {
        "endpoint_url": settings.S3_ENDPOINT_URL,
        "aws_access_key_id": settings.S3_ACCESS_KEY,
        "aws_secret_access_key": settings.S3_SECRET_KEY,
        "region_name": settings.S3_REGION,
        "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    }


def build_key(purpose: str, owner_id: uuid.UUID, filename: str, content_type: str) -> str:
    """Namespaced, unguessable object key."""
    extension = _EXTENSIONS.get(content_type) or mimetypes.guess_extension(content_type) or ""
    return f"{purpose}/{owner_id}/{uuid.uuid4().hex}{extension}"


def validate_upload(content_type: str, size: int) -> None:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise ValidationError(
            "unsupported file type",
            code="file_type_unsupported",
            details={"allowed": sorted(ALLOWED_CONTENT_TYPES)},
        )
    if size <= 0:
        raise ValidationError("empty file", code="file_empty")
    if size > settings.MAX_UPLOAD_BYTES:
        raise ValidationError(
            "file too large",
            code="file_too_large",
            details={"max_bytes": settings.MAX_UPLOAD_BYTES},
        )


async def ensure_bucket() -> None:
    """Create the bucket on first boot; harmless when it already exists."""
    async with _session().client("s3", **_client_kwargs()) as s3:
        try:
            await s3.head_bucket(Bucket=settings.S3_BUCKET)
        except ClientError:
            try:
                await s3.create_bucket(Bucket=settings.S3_BUCKET)
                log.info("storage.bucket_created", bucket=settings.S3_BUCKET)
            except ClientError as exc:
                log.error("storage.bucket_failed", error=str(exc))


async def upload(data: bytes, key: str, content_type: str) -> StoredObject:
    validate_upload(content_type, len(data))
    checksum = hashlib.sha256(data).hexdigest()
    async with _session().client("s3", **_client_kwargs()) as s3:
        try:
            await s3.put_object(
                Bucket=settings.S3_BUCKET,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata={"checksum": checksum},
            )
        except ClientError as exc:
            log.error("storage.upload_failed", error=str(exc))
            raise ExternalServiceError("file upload failed", code="storage_failed") from exc
    return StoredObject(key=key, size=len(data), content_type=content_type, checksum=checksum)


async def presigned_url(key: str, *, filename: str | None = None) -> str:
    """Time-limited download URL. Never handed out without an access check first."""
    params: dict = {"Bucket": settings.S3_BUCKET, "Key": key}
    if filename:
        params["ResponseContentDisposition"] = f'inline; filename="{filename}"'
    async with _session().client("s3", **_client_kwargs()) as s3:
        url = await s3.generate_presigned_url(
            "get_object", Params=params, ExpiresIn=settings.S3_PRESIGN_TTL_SECONDS
        )
    if settings.S3_PUBLIC_ENDPOINT_URL:
        url = url.replace(settings.S3_ENDPOINT_URL, settings.S3_PUBLIC_ENDPOINT_URL, 1)
    return url


async def delete(key: str) -> None:
    async with _session().client("s3", **_client_kwargs()) as s3:
        try:
            await s3.delete_object(Bucket=settings.S3_BUCKET, Key=key)
        except ClientError as exc:
            log.warning("storage.delete_failed", error=str(exc))


async def download(key: str) -> bytes:
    async with _session().client("s3", **_client_kwargs()) as s3:
        try:
            response = await s3.get_object(Bucket=settings.S3_BUCKET, Key=key)
            return await response["Body"].read()
        except ClientError as exc:
            raise ExternalServiceError("file download failed", code="storage_failed") from exc
