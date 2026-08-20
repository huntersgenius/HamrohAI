"""Typed application errors, translated into localized API responses."""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all expected (non-bug) failures.

    ``code`` is a stable machine-readable key. The mobile client localizes on
    ``code``; ``message`` is a localized fallback for logs and non-app clients.
    """

    status_code: int = 400
    code: str = "bad_request"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code or self.code
        self.status_code = status_code or self.status_code
        self.message = message or self.code
        self.details = details or {}
        super().__init__(self.message)


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"


class ValidationError(AppError):
    status_code = 422
    code = "validation_error"


class AuthError(AppError):
    status_code = 401
    code = "unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"


class PaymentError(AppError):
    status_code = 402
    code = "payment_failed"


class ExternalServiceError(AppError):
    status_code = 502
    code = "external_service_error"
