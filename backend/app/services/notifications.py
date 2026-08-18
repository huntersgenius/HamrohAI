"""Notification outbox (spec 9).

Persist first, deliver second. The database row is the source of truth for the
in-app list, so a push-provider outage degrades to "no banner" rather than "the
user never learns about it".

Every notification is rendered in the *recipient's* locale, never the requester's.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import translate
from app.core.logging import get_logger
from app.models.enums import NotificationType
from app.models.notification import Notification
from app.models.user import DeviceToken, User

log = get_logger(__name__)

# Preference key each notification type is gated on. Types not listed here are
# operationally important and always delivered.
_PREFERENCE_KEYS: dict[NotificationType, str] = {
    NotificationType.PATIENT_ADDED: "new_patient",
    NotificationType.CONSULTATION_NEW: "new_consultation",
    NotificationType.WALLET_UPDATED: "wallet",
    NotificationType.MEDICATION_DUE: "medication",
    NotificationType.CHECKIN_DUE: "checkin",
    NotificationType.WEEKLY_REPORT: "weekly_report",
}


async def queue_notification(
    db: AsyncSession,
    *,
    user: User,
    type: NotificationType,
    title_key: str,
    body_key: str,
    params: dict | None = None,
    data: dict | None = None,
    dedupe_key: str | None = None,
) -> Notification | None:
    """Create a notification and hand it to the push transport.

    Returns ``None`` when the user opted out of this category, or when
    ``dedupe_key`` matches an existing row (a retried job).
    """
    preference_key = _PREFERENCE_KEYS.get(type)
    if preference_key and not user.wants(preference_key):
        return None

    if dedupe_key:
        exists = await db.scalar(
            sa.select(Notification.id).where(Notification.dedupe_key == dedupe_key)
        )
        if exists:
            return None

    locale = user.locale or "uz"
    notification = Notification(
        user_id=user.id,
        type=type,
        title=translate(title_key, locale, **(params or {})),
        body=translate(body_key, locale, **(params or {})),
        data=data or {},
        locale=locale,
        dedupe_key=dedupe_key,
    )
    db.add(notification)
    await db.flush()

    await _deliver(db, user, notification)
    return notification


async def _deliver(db: AsyncSession, user: User, notification: Notification) -> None:
    if not user.notify_push_enabled:
        return
    tokens = list(
        (
            await db.scalars(
                sa.select(DeviceToken).where(
                    DeviceToken.user_id == user.id, DeviceToken.is_active.is_(True)
                )
            )
        ).all()
    )
    if not tokens:
        return

    from app.services.push import send_push

    payload = {
        "notification_id": str(notification.id),
        "type": notification.type.value,
        **{k: str(v) for k, v in (notification.data or {}).items()},
    }
    result = await send_push(
        [token.token for token in tokens],
        title=notification.title,
        body=notification.body,
        data=payload,
    )
    now = datetime.now(UTC)
    if result.delivered:
        notification.pushed_at = now
    if result.error:
        notification.push_error = result.error[:255]
    # A token the provider rejects is dead; stop sending to it.
    if result.invalid_tokens:
        await db.execute(
            sa.update(DeviceToken)
            .where(DeviceToken.token.in_(result.invalid_tokens))
            .values(is_active=False)
        )
    await db.flush()


async def mark_read(
    db: AsyncSession, user_id: uuid.UUID, ids: list[uuid.UUID] | None, *, all_: bool = False
) -> int:
    stmt = sa.update(Notification).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)
    )
    if not all_:
        if not ids:
            return 0
        stmt = stmt.where(Notification.id.in_(ids))
    result = await db.execute(stmt.values(read_at=datetime.now(UTC)))
    return result.rowcount or 0


async def unread_count(db: AsyncSession, user_id: uuid.UUID) -> int:
    return (
        await db.scalar(
            sa.select(sa.func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        )
    ) or 0
