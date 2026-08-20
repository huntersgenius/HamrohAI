"""Medical specialties and their recommended consultation prices.

The list is extendable (spec 4.1: "kengaytiriladigan ro'yxat"). Prices are the
system's *recommendation*; a doctor may override their own price (spec 7).
"""

from __future__ import annotations

from typing import Final, TypedDict


class Specialty(TypedDict):
    code: str
    name: dict[str, str]
    recommended_price_uzs: int


SPECIALTIES: Final[list[Specialty]] = [
    {
        "code": "therapist",
        "name": {"uz": "Terapevt", "ru": "Терапевт", "en": "General practitioner"},
        "recommended_price_uzs": 30_000,
    },
    {
        "code": "endocrinologist",
        "name": {"uz": "Endokrinolog", "ru": "Эндокринолог", "en": "Endocrinologist"},
        "recommended_price_uzs": 50_000,
    },
    {
        "code": "cardiologist",
        "name": {"uz": "Kardiolog", "ru": "Кардиолог", "en": "Cardiologist"},
        "recommended_price_uzs": 60_000,
    },
    {
        "code": "dentist",
        "name": {"uz": "Stomatolog", "ru": "Стоматолог", "en": "Dentist"},
        "recommended_price_uzs": 40_000,
    },
    {
        "code": "neurologist",
        "name": {"uz": "Nevrolog", "ru": "Невролог", "en": "Neurologist"},
        "recommended_price_uzs": 55_000,
    },
    {
        "code": "pediatrician",
        "name": {"uz": "Pediatr", "ru": "Педиатр", "en": "Pediatrician"},
        "recommended_price_uzs": 40_000,
    },
    {
        "code": "gynecologist",
        "name": {"uz": "Ginekolog", "ru": "Гинеколог", "en": "Gynecologist"},
        "recommended_price_uzs": 55_000,
    },
    {
        "code": "urologist",
        "name": {"uz": "Urolog", "ru": "Уролог", "en": "Urologist"},
        "recommended_price_uzs": 55_000,
    },
    {
        "code": "pulmonologist",
        "name": {"uz": "Pulmonolog", "ru": "Пульмонолог", "en": "Pulmonologist"},
        "recommended_price_uzs": 55_000,
    },
    {
        "code": "gastroenterologist",
        "name": {
            "uz": "Gastroenterolog",
            "ru": "Гастроэнтеролог",
            "en": "Gastroenterologist",
        },
        "recommended_price_uzs": 55_000,
    },
    {
        "code": "dermatologist",
        "name": {"uz": "Dermatolog", "ru": "Дерматолог", "en": "Dermatologist"},
        "recommended_price_uzs": 45_000,
    },
    {
        "code": "ophthalmologist",
        "name": {"uz": "Oftalmolog", "ru": "Офтальмолог", "en": "Ophthalmologist"},
        "recommended_price_uzs": 50_000,
    },
    {
        "code": "otolaryngologist",
        "name": {"uz": "LOR shifokori", "ru": "ЛОР-врач", "en": "ENT specialist"},
        "recommended_price_uzs": 45_000,
    },
    {
        "code": "nephrologist",
        "name": {"uz": "Nefrolog", "ru": "Нефролог", "en": "Nephrologist"},
        "recommended_price_uzs": 60_000,
    },
    {
        "code": "rheumatologist",
        "name": {"uz": "Revmatolog", "ru": "Ревматолог", "en": "Rheumatologist"},
        "recommended_price_uzs": 55_000,
    },
    {
        "code": "psychiatrist",
        "name": {"uz": "Psixiatr", "ru": "Психиатр", "en": "Psychiatrist"},
        "recommended_price_uzs": 60_000,
    },
]

SPECIALTY_CODES: Final[set[str]] = {s["code"] for s in SPECIALTIES}
_BY_CODE: Final[dict[str, Specialty]] = {s["code"]: s for s in SPECIALTIES}

DEFAULT_PRICE_UZS: Final[int] = 40_000


def get_specialty(code: str) -> Specialty | None:
    return _BY_CODE.get(code)


def recommended_price(code: str) -> int:
    spec = _BY_CODE.get(code)
    return spec["recommended_price_uzs"] if spec else DEFAULT_PRICE_UZS


def specialty_name(code: str, locale: str = "uz") -> str:
    spec = _BY_CODE.get(code)
    if not spec:
        return code
    return spec["name"].get(locale) or spec["name"]["uz"]
