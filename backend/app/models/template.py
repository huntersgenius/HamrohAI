"""Diagnosis templates (spec 6).

A template declares which indicators are tracked, which questions the patient is
asked and how often, and how each trend chart is configured. When a doctor types
a diagnosis, the matching template is selected automatically and applied
immediately — it is the default, not a suggestion.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, JSONType, TimestampMixin, UUIDPrimaryKeyMixin


class DiagnosisTemplate(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "diagnosis_templates"

    code: Mapped[str] = mapped_column(sa.String(48), unique=True, nullable=False, index=True)
    # Localized names: {"uz": "...", "ru": "...", "en": "..."}
    name: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    description: Mapped[dict] = mapped_column(JSONType, default=dict, nullable=False)
    specialty: Mapped[str | None] = mapped_column(sa.String(64), nullable=True, index=True)
    icd10: Mapped[str | None] = mapped_column(sa.String(16), nullable=True)

    # Lower-cased keywords in all three languages used to auto-match free-text
    # diagnoses, e.g. ["qandli diabet", "diabet", "сахарный диабет", "diabetes"].
    keywords: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    # [{key, label:{uz,ru,en}, unit, target_min, target_max,
    #   critical_min, critical_max, decimals, chart_type, value_type, sort_order}]
    metrics: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    # [{key, metric_key, prompt:{uz,ru,en}, type, options, frequency, times_per_day,
    #   days_of_week, required}]
    checkin_questions: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    # Protocol slugs this template is allowed to draw RAG answers from (spec 8).
    protocol_slugs: Mapped[list] = mapped_column(JSONType, default=list, nullable=False)

    is_active: Mapped[bool] = mapped_column(sa.Boolean, default=True, nullable=False)
    version: Mapped[int] = mapped_column(sa.Integer, default=1, nullable=False)
    sort_order: Mapped[int] = mapped_column(sa.Integer, default=100, nullable=False)

    def localized_name(self, locale: str = "uz") -> str:
        names = self.name or {}
        return names.get(locale) or names.get("uz") or self.code
