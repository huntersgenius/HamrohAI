"""SQLAlchemy models.

Imported as a package so that ``Base.metadata`` is fully populated for Alembic
autogeneration and for the test-suite's ``create_all``.
"""

from app.models.ai import (
    AiEscalation,
    AiMessage,
    Protocol,
    ProtocolChunk,
    ThreadMessage,
    WeeklyReport,
)
from app.models.base import Base
from app.models.billing import Payment, PayoutRequest, Wallet, WalletTransaction
from app.models.care import (
    CareThread,
    CheckinSubmission,
    Diagnosis,
    DiagnosisChangeRequest,
    Document,
    Medication,
    MedicationDose,
    MetricReading,
    MetricSeries,
    PatientInvite,
    ReminderCall,
)
from app.models.consultation import Consultation
from app.models.notification import AuditLog, Notification
from app.models.profile import DoctorProfile, DoctorSubscription, PatientProfile
from app.models.template import DiagnosisTemplate
from app.models.user import AuthIdentity, DeviceToken, OtpChallenge, RefreshSession, User

__all__ = [
    "AiEscalation",
    "AiMessage",
    "AuditLog",
    "AuthIdentity",
    "Base",
    "CareThread",
    "CheckinSubmission",
    "Consultation",
    "DeviceToken",
    "Diagnosis",
    "DiagnosisChangeRequest",
    "DiagnosisTemplate",
    "DoctorProfile",
    "DoctorSubscription",
    "Document",
    "Medication",
    "MedicationDose",
    "MetricReading",
    "MetricSeries",
    "Notification",
    "OtpChallenge",
    "PatientInvite",
    "PatientProfile",
    "Payment",
    "PayoutRequest",
    "Protocol",
    "ProtocolChunk",
    "RefreshSession",
    "ReminderCall",
    "ThreadMessage",
    "User",
    "Wallet",
    "WalletTransaction",
    "WeeklyReport",
]
