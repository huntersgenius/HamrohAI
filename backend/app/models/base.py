"""Declarative base, shared column types and mixins."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Portable column types: PostgreSQL in production, SQLite in the test-suite.
UUIDType = PGUUID(as_uuid=True).with_variant(sa.String(36), "sqlite")
JSONType = JSONB().with_variant(sa.JSON(), "sqlite")
TimestampType = sa.DateTime(timezone=True)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {
        dict: JSONType,
        list: JSONType,
        datetime: TimestampType,
        uuid.UUID: UUIDType,
    }


class UUIDPrimaryKeyMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=uuid.uuid4, sort_order=-100
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        TimestampType, default=utcnow, server_default=sa.func.now(), nullable=False, sort_order=100
    )
    updated_at: Mapped[datetime] = mapped_column(
        TimestampType,
        default=utcnow,
        onupdate=utcnow,
        server_default=sa.func.now(),
        nullable=False,
        sort_order=101,
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        TimestampType, nullable=True, sort_order=102
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
