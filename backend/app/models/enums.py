"""Every enumerated domain value in one place.

Stored as VARCHAR + CHECK constraint (``native_enum=False``) so that adding a
value is an ordinary migration instead of a PostgreSQL type surgery.
"""

from __future__ import annotations

from enum import StrEnum

import sqlalchemy as sa


def enum_column(enum_cls: type[StrEnum], name: str) -> sa.Enum:
    return sa.Enum(
        enum_cls,
        name=name,
        native_enum=False,
        length=40,
        values_callable=lambda e: [item.value for item in e],
    )


class UserRole(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    # Reserved for the future admin panel (spec 1: architecture must be ready,
    # but no admin UI ships in the MVP).
    ADMIN = "admin"


class AuthProvider(StrEnum):
    PHONE = "phone"
    GOOGLE = "google"
    TELEGRAM = "telegram"


class OtpPurpose(StrEnum):
    LOGIN = "login"
    LINK_PHONE = "link_phone"
    CHANGE_PHONE = "change_phone"


class DoctorVerificationStatus(StrEnum):
    PENDING = "pending"  # "tekshiruv kutilmoqda"
    APPROVED = "approved"
    REJECTED = "rejected"


class SubscriptionStatus(StrEnum):
    TRIAL = "trial"
    ACTIVE = "active"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class SubscriptionPlan(StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class CareThreadKind(StrEnum):
    """A care thread is the isolation boundary for all clinical data (spec 2.2)."""

    DOCTOR = "doctor"  # patient <-> one specific doctor
    PERSONAL = "personal"  # self-tracked, not yet shared with any doctor


class CareThreadStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class DiagnosisStatus(StrEnum):
    UNVERIFIED = "unverified"  # entered by the patient, not yet reviewed
    VERIFIED = "verified"  # entered or confirmed by the doctor


class ChangeRequestStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class DoseStatus(StrEnum):
    PENDING = "pending"
    TAKEN = "taken"
    MISSED = "missed"
    SKIPPED = "skipped"


class DoseConfirmationChannel(StrEnum):
    APP = "app"
    IVR = "ivr"
    DOCTOR = "doctor"


class ReadingSource(StrEnum):
    PATIENT = "patient"
    DOCTOR = "doctor"
    IMPORT = "import"
    DEVICE = "device"


class InviteStatus(StrEnum):
    ISSUED = "issued"
    REDEEMED = "redeemed"
    EXPIRED = "expired"
    REVOKED = "revoked"


class ConsultationStatus(StrEnum):
    DRAFT = "draft"  # created, payment not completed
    PENDING_PAYMENT = "pending_payment"
    OPEN = "open"  # paid, visible to matching doctors
    CLAIMED = "claimed"  # a doctor accepted it
    ANSWERED = "answered"
    RATED = "rated"
    REFUNDED = "refunded"  # 24h SLA missed
    CANCELLED = "cancelled"


class ConsultationTargeting(StrEnum):
    DIRECT = "direct"  # patient picked a specific doctor
    MATCHED = "matched"  # system matched by specialty (doctor sees "Anonim")


class PaymentProvider(StrEnum):
    CLICK = "click"
    PAYME = "payme"


class PaymentPurpose(StrEnum):
    CONSULTATION = "consultation"
    SUBSCRIPTION = "subscription"


class PaymentStatus(StrEnum):
    CREATED = "created"
    PENDING = "pending"  # provider reserved / prepared
    PAID = "paid"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"
    FAILED = "failed"


class WalletTxnType(StrEnum):
    CONSULTATION_EARNING = "consultation_earning"
    PAYOUT = "payout"
    ADJUSTMENT = "adjustment"
    REVERSAL = "reversal"


class PayoutStatus(StrEnum):
    REQUESTED = "requested"
    PROCESSING = "processing"
    PAID = "paid"
    REJECTED = "rejected"


class NotificationType(StrEnum):
    PATIENT_ADDED = "patient_added"
    CONSULTATION_NEW = "consultation_new"
    CONSULTATION_ANSWERED = "consultation_answered"
    CONSULTATION_REFUNDED = "consultation_refunded"
    MEDICATION_DUE = "medication_due"
    CHECKIN_DUE = "checkin_due"
    AI_ESCALATION = "ai_escalation"
    DIAGNOSIS_PENDING = "diagnosis_pending"
    DIAGNOSIS_CHANGE_REQUEST = "diagnosis_change_request"
    WALLET_UPDATED = "wallet_updated"
    WEEKLY_REPORT = "weekly_report"
    DOCTOR_REPLIED = "doctor_replied"


class DevicePlatform(StrEnum):
    ANDROID = "android"
    IOS = "ios"


class MessageRole(StrEnum):
    PATIENT = "patient"
    ASSISTANT = "assistant"
    DOCTOR = "doctor"
    SYSTEM = "system"


class AiOutcome(StrEnum):
    ANSWERED = "answered"  # answered from protocol
    ESCALATED = "escalated"  # forwarded to the assigned doctor
    NO_DOCTOR = "no_doctor"  # told the patient to use paid consultation
    EMERGENCY = "emergency"  # red-flag response
    REFUSED = "refused"  # out of scope / unsafe request


class DocumentPurpose(StrEnum):
    DOCTOR_LICENSE = "doctor_license"
    CARE_THREAD = "care_thread"
    CONSULTATION = "consultation"


class CallStatus(StrEnum):
    SCHEDULED = "scheduled"
    PLACED = "placed"
    CONFIRMED = "confirmed"
    NO_ANSWER = "no_answer"
    FAILED = "failed"
    CANCELLED = "cancelled"
