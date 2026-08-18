"""Structured logging with medical-data redaction."""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import settings

# Keys that must never reach the log sink: they carry PHI or credentials.
SENSITIVE_KEYS = {
    "password",
    "otp",
    "code",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "diagnosis",
    "diagnosis_text",
    "question",
    "answer",
    "message",
    "note",
    "content",
    "secret",
    "signature",
    "phone",
}


def _redact(_logger: Any, _name: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    for key in list(event_dict.keys()):
        if key.lower() in SENSITIVE_KEYS and event_dict[key] is not None:
            event_dict[key] = "[redacted]"
    return event_dict


def configure_logging() -> None:
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
    )
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.dev.ConsoleRenderer()
        if not settings.is_production
        else structlog.processors.JSONRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.DEBUG if settings.DEBUG else logging.INFO
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
