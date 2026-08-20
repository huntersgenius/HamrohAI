"""Notification outbox and audit log."""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import (
    Base,
    JSONType,
    TimestampMixin,
    TimestampType,
    UUIDPrimaryKeyMixin,
    UUIDType,
)
from app.models.enums import NotificationType, enum_column


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Persisted notification. Written first, delivered second, so a push
    provider outage never loses the record — the in-app list stays correct."""

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[NotificationType] = mapped_column(
        enum_column(NotificationType, "notification_type"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Deep-link payload consumed by the app router, e.g.
    # {"screen": "consultation", "consultation_id": "..."}
    data: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    locale: Mapped[str] = mapped_column(sa.String(5), default="uz", nullable=False)

    read_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    pushed_at: Mapped[datetime | None] = mapped_column(TimestampType, nullable=True)
    push_error: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    # Prevents duplicate sends when a job retries.
    dedupe_key: Mapped[str | None] = mapped_column(sa.String(160), nullable=True)

    __table_args__ = (
        sa.UniqueConstraint("dedupe_key", name="uq_notification_dedupe"),
        sa.Index("ix_notification_user_created", "user_id", "created_at"),
    )


class AuditLog(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Append-only trail for access to medical data and money movement.

    Required for a medical platform: who looked at or changed what, and when.
    """

    __tablename__ = "audit_logs"

    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(sa.String(64), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(sa.String(48), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    care_thread_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True, index=True)
    # Never contains clinical content — only identifiers and changed field names.
    meta: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
