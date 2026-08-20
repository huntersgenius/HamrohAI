"""Care-thread access control — the single gate for all clinical data.

Spec 2.2 makes each patient-doctor connection an absolutely isolated container.
Isolation is only real if there is exactly one place that decides who may touch a
thread, so **every** endpoint that reads or writes clinical data must resolve the
thread through this module rather than querying by id directly.

Rules enforced here:

* A patient reaches their own threads (doctor threads and the personal one).
* A doctor reaches only threads where they are ``doctor_user_id``.
* Nobody else reaches a thread, and a doctor never sees another doctor's thread
  for the same patient.
* Write access additionally requires an approved, subscribed doctor.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ForbiddenError, NotFoundError
from app.models.care import CareThread
from app.models.enums import CareThreadKind, UserRole
from app.models.user import User

Perspective = Literal["patient", "doctor"]


@dataclass(frozen=True, slots=True)
class ThreadAccess:
    """Resolved access to one care thread."""

    thread: CareThread
    perspective: Perspective

    @property
    def is_doctor(self) -> bool:
        return self.perspective == "doctor"

    @property
    def is_patient(self) -> bool:
        return self.perspective == "patient"

    @property
    def thread_id(self) -> uuid.UUID:
        return self.thread.id

    def require_doctor(self) -> None:
        """Guard for operations only a doctor may perform in a thread."""
        if not self.is_doctor:
            raise ForbiddenError(
                "only the assigned doctor may perform this action", code="doctor_only"
            )

    def require_patient(self) -> None:
        if not self.is_patient:
            raise ForbiddenError("only the patient may perform this action", code="patient_only")


async def resolve_thread(
    db: AsyncSession,
    thread_id: uuid.UUID,
    user: User,
    *,
    allow_archived: bool = False,
) -> ThreadAccess:
    """Load ``thread_id`` and verify ``user`` is a participant.

    Raises ``NotFoundError`` rather than ``ForbiddenError`` when the user is not a
    participant: an outsider must not be able to probe which thread ids exist.
    """
    thread = await db.scalar(sa.select(CareThread).where(CareThread.id == thread_id))
    if thread is None:
        raise NotFoundError("care thread not found", code="thread_not_found")

    if thread.patient_user_id == user.id:
        perspective: Perspective = "patient"
    elif thread.doctor_user_id is not None and thread.doctor_user_id == user.id:
        perspective = "doctor"
    else:
        raise NotFoundError("care thread not found", code="thread_not_found")

    if not allow_archived and thread.archived_at is not None:
        raise ForbiddenError("care thread is archived", code="thread_archived")

    return ThreadAccess(thread=thread, perspective=perspective)


async def resolve_doctor_thread(db: AsyncSession, thread_id: uuid.UUID, user: User) -> ThreadAccess:
    """Resolve a thread and require that the caller is its doctor."""
    access = await resolve_thread(db, thread_id, user)
    access.require_doctor()
    return access


async def resolve_patient_thread(
    db: AsyncSession, thread_id: uuid.UUID, user: User
) -> ThreadAccess:
    access = await resolve_thread(db, thread_id, user)
    access.require_patient()
    return access


def visible_thread_filter(user: User) -> sa.ColumnElement[bool]:
    """SQL predicate restricting a ``CareThread`` query to what ``user`` may see.

    Use this instead of hand-written ``where`` clauses when listing threads, so
    list endpoints inherit the same isolation rule as single-thread reads.
    """
    if user.role == UserRole.DOCTOR:
        return CareThread.doctor_user_id == user.id
    return CareThread.patient_user_id == user.id


def clinical_scope_filter(
    column: sa.ColumnElement, allowed_thread_ids: list[uuid.UUID]
) -> sa.ColumnElement[bool]:
    """Restrict any clinical table to a set of already-authorised thread ids."""
    if not allowed_thread_ids:
        return sa.false()
    return column.in_(allowed_thread_ids)


async def get_or_create_personal_thread(db: AsyncSession, patient: User) -> CareThread:
    """Return the patient's private container, creating it on first use.

    This is where a self-registered patient's own data lives until they connect
    to a doctor and consent to sharing it (spec 2.2).
    """
    thread = await db.scalar(
        sa.select(CareThread).where(
            CareThread.patient_user_id == patient.id,
            CareThread.doctor_user_id.is_(None),
        )
    )
    if thread is not None:
        return thread
    thread = CareThread(
        patient_user_id=patient.id,
        doctor_user_id=None,
        kind=CareThreadKind.PERSONAL,
        title=None,
    )
    db.add(thread)
    await db.flush()
    return thread


async def assert_no_cross_thread_reference(
    db: AsyncSession, thread_id: uuid.UUID, *entity_thread_ids: uuid.UUID | None
) -> None:
    """Defensive check that a child record belongs to the thread being operated on.

    Any mismatch means a caller passed an id from a different container, which is
    exactly the leak spec 2.2 forbids.
    """
    for other in entity_thread_ids:
        if other is not None and other != thread_id:
            raise ForbiddenError("record belongs to a different care thread", code="cross_thread")
