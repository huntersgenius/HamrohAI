"""Diagnosis-template matching and application (spec 6).

When a doctor types a diagnosis, the matching template is selected
*automatically and immediately* — it is the default state, not a hint. The doctor
can still change it from the dropdown, and can edit/remove/add the resulting
indicators at any time afterwards.

Matching is deliberately lexical rather than model-based: it must be
deterministic, explainable, offline, and work identically in Uzbek, Russian and
English.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.care import MetricSeries
from app.models.template import DiagnosisTemplate

# Uzbek Latin uses several apostrophe-like characters interchangeably
# (oʻ / o' / o` / o‘). They are folded to a plain apostrophe before matching.
_APOSTROPHES = {"‘", "’", "ʻ", "ʼ", "`", "´", "ʹ"}


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value or "").lower()
    for ch in _APOSTROPHES:
        text = text.replace(ch, "'")
    text = re.sub(r"[^\w'\s]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


@dataclass(frozen=True, slots=True)
class TemplateMatch:
    template: DiagnosisTemplate | None
    confidence: float
    alternatives: list[tuple[DiagnosisTemplate, float]]


def _score(diagnosis_norm: str, keyword: str) -> float:
    """Score one keyword against the normalised diagnosis text.

    Longer keywords are worth more: "qandli diabet" must beat a bare "diabet" so
    a specific template wins over a generic one.
    """
    kw = normalize_text(keyword)
    if not kw or kw not in diagnosis_norm:
        return 0.0
    # Whole-phrase hits score higher than hits inside a larger word.
    boundary = re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", diagnosis_norm) is not None
    base = min(len(kw) / 24.0, 1.0)
    return base * (1.0 if boundary else 0.6)


async def match_template(db: AsyncSession, diagnosis_text: str, *, limit: int = 4) -> TemplateMatch:
    """Find the best template for a free-text diagnosis."""
    norm = normalize_text(diagnosis_text)
    if not norm:
        return TemplateMatch(None, 0.0, [])

    templates = list(
        (
            await db.scalars(
                sa.select(DiagnosisTemplate)
                .where(DiagnosisTemplate.is_active.is_(True))
                .order_by(DiagnosisTemplate.sort_order)
            )
        ).all()
    )

    scored: list[tuple[DiagnosisTemplate, float]] = []
    for template in templates:
        best = 0.0
        for keyword in template.keywords or []:
            if isinstance(keyword, str):
                best = max(best, _score(norm, keyword))
        # The localized names count as keywords too.
        for name in (template.name or {}).values():
            if isinstance(name, str):
                best = max(best, _score(norm, name) * 0.9)
        if best > 0:
            scored.append((template, round(best, 3)))

    if not scored:
        return TemplateMatch(None, 0.0, [(t, 0.0) for t in templates[:limit]])

    scored.sort(key=lambda pair: (-pair[1], pair[0].sort_order))
    best_template, best_score = scored[0]
    return TemplateMatch(
        template=best_template,
        confidence=best_score,
        alternatives=scored[1:limit],
    )


async def apply_template_to_thread(
    db: AsyncSession,
    thread_id: uuid.UUID,
    template: DiagnosisTemplate,
    *,
    replace: bool = False,
) -> list[MetricSeries]:
    """Create the template's metric series inside a care thread.

    Idempotent by ``(thread_id, key)``: applying the same template twice updates
    the definitions instead of duplicating charts. Existing readings are never
    touched — a doctor switching templates keeps the patient's history.
    """
    existing = {
        series.key: series
        for series in (
            await db.scalars(
                sa.select(MetricSeries).where(MetricSeries.care_thread_id == thread_id)
            )
        ).all()
    }

    template_keys: set[str] = set()
    result: list[MetricSeries] = []

    for index, metric in enumerate(template.metrics or []):
        key = metric.get("key")
        if not key:
            continue
        template_keys.add(key)
        series = existing.get(key)
        if series is None:
            series = MetricSeries(
                care_thread_id=thread_id,
                key=key,
                source_template_id=template.id,
            )
            db.add(series)
        series.label = metric.get("label") or {"uz": key}
        series.unit = metric.get("unit", "")
        series.value_type = metric.get("value_type", "number")
        series.target_min = metric.get("target_min")
        series.target_max = metric.get("target_max")
        series.critical_min = metric.get("critical_min")
        series.critical_max = metric.get("critical_max")
        series.decimals = int(metric.get("decimals", 1))
        series.chart_type = metric.get("chart_type", "line")
        series.sort_order = int(metric.get("sort_order", index))
        series.is_active = True
        result.append(series)

    if replace:
        # Charts from the previous template are hidden, not deleted, so that the
        # readings behind them survive and can be restored.
        for key, series in existing.items():
            if key not in template_keys:
                series.is_active = False

    await db.flush()
    return result


def checkin_questions_for(template: DiagnosisTemplate | None, *, slot: str = "day") -> list[dict]:
    """Questions the patient answers in the "Bugun" tab for a given slot."""
    if template is None:
        return []
    questions = []
    for question in template.checkin_questions or []:
        slots = question.get("slots") or ["day"]
        if slot in slots or "day" in slots:
            questions.append(question)
    return questions
