"""Mock mode for every external integration.

Hamroh depends on five outside services: SMS (Eskiz / Play Mobile), voice calls
(Twilio), push (FCM), payments (Click / Payme) and the AI model. None of them
can be reached before the merchant and operator applications are approved, and
the credentials simply do not exist yet.

Rather than leave those code paths untested until the keys arrive, each
integration has a *mock mode*: the real provider object is swapped for one that
records what would have been sent and returns the success value the real API
would have returned. **No HTTP request leaves the process.**

Mode is chosen per integration by an environment variable::

    SMS_MODE=mock      IVR_MODE=mock      PUSH_MODE=mock
    PAYMENT_MODE=mock  AI_MODE=mock

Everything a mock "sends" lands in :data:`outbox`, so a developer or a test can
read back the OTP code, the reminder call or the push that a real provider would
have delivered. In non-production environments the outbox is also exposed over
HTTP at ``/api/v1/mock/outbox``.

The outbox is process-local and deliberately in-memory: it is a development
aid, not durable state.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

MockKind = Literal["sms", "ivr", "push", "payment", "ai"]

# How many simulated messages are kept before the oldest is dropped.
OUTBOX_MAX_ITEMS = 200


@dataclass(frozen=True, slots=True)
class MockEvent:
    """One outbound message that mock mode swallowed instead of sending."""

    seq: int
    kind: MockKind
    target: str
    summary: str
    payload: dict[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_dict(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "kind": self.kind,
            "target": self.target,
            "summary": self.summary,
            "payload": self.payload,
            "at": self.at.isoformat(),
        }


class MockOutbox:
    """Bounded, thread-safe record of everything mock mode simulated."""

    def __init__(self, max_items: int = OUTBOX_MAX_ITEMS) -> None:
        self._items: deque[MockEvent] = deque(maxlen=max_items)
        self._lock = threading.Lock()
        self._seq = 0

    def record(
        self, kind: MockKind, target: str, summary: str, **payload: Any
    ) -> MockEvent:
        with self._lock:
            self._seq += 1
            event = MockEvent(
                seq=self._seq, kind=kind, target=target, summary=summary, payload=payload
            )
            self._items.append(event)
        # The log line is intentionally coarse: message bodies may carry OTP
        # codes and clinical text, which app.core.logging redacts elsewhere.
        log.info("mock.sent", kind=kind, target=target[-4:] if target else "", seq=event.seq)
        return event

    def all(self, kind: MockKind | None = None, limit: int | None = None) -> list[MockEvent]:
        with self._lock:
            items = list(self._items)
        if kind is not None:
            items = [e for e in items if e.kind == kind]
        items.reverse()  # newest first
        return items[:limit] if limit else items

    def latest(self, kind: MockKind | None = None) -> MockEvent | None:
        found = self.all(kind=kind, limit=1)
        return found[0] if found else None

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._items)


outbox = MockOutbox()


# --------------------------------------------------------------- mode helpers
def sms_is_mocked() -> bool:
    # SMS_PROVIDER="console" predates SMS_MODE and still means the same thing.
    return settings.SMS_MODE == "mock" or settings.SMS_PROVIDER == "console"


def ivr_is_mocked() -> bool:
    return settings.IVR_MODE == "mock" or settings.IVR_PROVIDER == "console"


def push_is_mocked() -> bool:
    return (
        settings.PUSH_MODE == "mock"
        or settings.PUSH_PROVIDER != "fcm"
        or not settings.FCM_CREDENTIALS_JSON
    )


def payments_are_mocked() -> bool:
    return settings.PAYMENT_MODE == "mock"


def ai_is_mocked() -> bool:
    return settings.AI_MODE == "mock" or settings.AI_PROVIDER == "console"


def mocked_integrations() -> dict[str, bool]:
    """Reported by ``/health`` so a deployment can be audited at a glance."""
    return {
        "sms": sms_is_mocked(),
        "ivr": ivr_is_mocked(),
        "push": push_is_mocked(),
        "payments": payments_are_mocked(),
        "ai": ai_is_mocked(),
    }
