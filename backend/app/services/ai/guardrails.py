"""Safety classification for AI companion input and output (spec 8).

Three checks run before anything reaches the model, and one runs after:

1. **Emergency** — red-flag symptoms short-circuit everything and return the
   emergency script. No retrieval, no model call, no waiting.
2. **Diagnosis / prescription requests** — "what disease do I have", "should I
   raise the dose" are never answered; they escalate to the doctor.
3. **Prompt injection** — attempts to redefine the assistant's role are
   stripped; the patient's message is data, never instructions.
4. **Output validation** — an answer that drifted into diagnosing or dosing is
   discarded and replaced with an escalation.

Keyword rules are used rather than a classifier because they are auditable and
fail closed in all three languages.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

_APOSTROPHES = {"‘", "’", "ʻ", "ʼ", "`", "´", "ʹ"}


class Verdict(StrEnum):
    ALLOW = "allow"
    EMERGENCY = "emergency"
    ESCALATE = "escalate"


# Symptoms that must never wait for an app reply.
#
# The distance windows are deliberately generous (~60 chars, roughly a clause):
# real messages put several words between the body part and the symptom
# ("ko'krak qafasida kuchli og'riq bor"), and both orders occur. Over-matching
# here costs an unnecessary "call 103" line; under-matching costs a missed
# emergency, so these fail towards caution.
EMERGENCY_PATTERNS: tuple[str, ...] = (
    # uz
    r"ko'?krak.{0,60}og'?ri",
    r"og'?ri.{0,60}ko'?krak",
    r"yurag\w*.{0,40}og'?ri",
    r"nafas.{0,40}(qis|ol\w*may|yeta?may|bo'?g'?il)",
    r"(bo'?g'?il|nafas\w*\s*qis)\w*",
    r"hush(i|dan)?\s*(ket|yo'?q)",
    r"falaj",
    r"tutqanoq",
    r"qon\s*ket(ish|yap|di)",
    r"o'?zimni\s*o'?ldir",
    r"jonimga\s*qasd",
    # ru
    r"бол[ьи].{0,60}(в\s*)?груд",
    r"груд\w*.{0,60}бол",
    r"сердц\w*.{0,40}бол",
    r"не\s*могу\s*дышать",
    r"нечем\s*дышать",
    r"задыха\w*",
    r"одышк\w*.{0,40}(сильн|тяжел)",
    r"потер\w*\s*сознани",
    r"без\s*сознани",
    r"судорог",
    r"кровотечени",
    r"парализ",
    r"покончить\s*с\s*собой",
    # en
    r"chest\s*(pain|tight|pressure)",
    r"pain.{0,40}(in\s*my\s*)?chest",
    r"can'?t\s*breathe",
    r"cannot\s*breathe",
    r"short(ness)?\s*of\s*breath.{0,40}(severe|bad|really)",
    r"passed?\s*out",
    r"unconscious",
    r"seizure",
    r"bleeding\s*(heavily|a\s*lot|won'?t\s*stop)",
    r"paral(ysis|ysed|yzed)",
    r"kill\s*myself",
    r"suicid",
)

# Requests for a diagnosis or a treatment decision — always the doctor's call.
DIAGNOSIS_PATTERNS: tuple[str, ...] = (
    # uz
    r"qanday\s*kasal",
    r"menda\s*(qanday|qaysi)?\s*kasallik",
    r"tashxis\s*(qo'?y|ayt|bering)",
    r"nima\s*bo'?l(gan|di)\s*menga",
    r"qaysi\s*dori(ni)?\s*(ich|qabul)",
    r"doza(ni|sini)?\s*(oshir|kamayt|o'?zgartir)",
    r"dori\s*(tavsiya|buyur|yoz)",
    r"davolash(ni)?\s*(bошlа|boshla|ayt)",
    # ru
    r"как(ая|ой)\s*у\s*меня\s*(болезнь|диагноз)",
    r"поставь?те?\s*диагноз",
    r"что\s*со\s*мной",
    r"како[ей]\s*лекарств",
    r"какую\s*таблетк",
    r"увеличить\s*дозу",
    r"уменьшить\s*дозу",
    r"измен(ить|ю)\s*дозу",
    r"назначь?те?\s*лечение",
    r"выпис(ать|ки)\s*лекарств",
    # en
    r"what\s*(disease|condition|illness)\s*do\s*i",
    r"diagnose\s*me",
    r"what'?s\s*wrong\s*with\s*me",
    r"which\s*(medicine|drug|pill)\s*should\s*i",
    r"(increase|decrease|change|adjust)\s*(my\s*)?dose",
    r"prescribe",
    r"can\s*i\s*stop\s*taking",
)

# Attempts to overwrite the assistant's instructions.
INJECTION_PATTERNS: tuple[str, ...] = (
    r"ignore\s*(all\s*)?(previous|prior|above)\s*instructions?",
    r"disregard\s*(your|the)\s*(rules|instructions|protocol)",
    r"you\s*are\s*(now|no\s*longer)\s*a?\s*\w+",
    r"pretend\s*(to\s*be|you\s*are)",
    r"act\s*as\s*(a|an)\s*(doctor|physician|nurse)",
    r"system\s*prompt",
    r"забудь\s*(все\s*)?(предыдущие\s*)?инструкц",
    r"игнорируй\s*(все\s*)?правил",
    r"ты\s*теперь\s*врач",
    r"представь,?\s*что\s*ты",
    r"oldingi\s*(barcha\s*)?ko'?rsatma",
    r"endi\s*sen\s*shifokorsan",
)

# Phrases an answer must never contain — a model that produced them has drifted
# outside the protocol, so the answer is dropped rather than shown.
UNSAFE_OUTPUT_PATTERNS: tuple[str, ...] = (
    r"sizda\s+\w+\s+kasalligi\s+bor",
    r"tashxis(ingiz)?\s*[:—-]\s*\w+",
    r"dozani\s*(oshiring|kamaytiring|o'?zgartiring)",
    r"у\s*вас\s+\w*\s*(болезнь|диагноз)\b",
    r"увеличьте\s*дозу",
    r"уменьшите\s*дозу",
    r"you\s*(have|are\s*suffering\s*from)\s+(diabetes|hypertension|asthma|cancer)",
    r"(increase|decrease)\s*your\s*dose",
    r"i\s*(diagnose|prescribe)",
)


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    for ch in _APOSTROPHES:
        text = text.replace(ch, "'")
    return re.sub(r"\s+", " ", text)


def _matches(text: str, patterns: tuple[str, ...]) -> str | None:
    for pattern in patterns:
        if re.search(pattern, text, flags=re.IGNORECASE | re.UNICODE):
            return pattern
    return None


@dataclass(frozen=True, slots=True)
class InputCheck:
    verdict: Verdict
    reason: str
    matched: str | None = None


def check_input(message: str) -> InputCheck:
    """Classify a patient message before retrieval."""
    text = _normalize(message)

    matched = _matches(text, EMERGENCY_PATTERNS)
    if matched:
        return InputCheck(Verdict.EMERGENCY, "emergency_symptom", matched)

    matched = _matches(text, INJECTION_PATTERNS)
    if matched:
        # Not an error: the patient may simply be curious. It is answered as an
        # ordinary out-of-scope question rather than obeyed.
        return InputCheck(Verdict.ESCALATE, "prompt_injection", matched)

    matched = _matches(text, DIAGNOSIS_PATTERNS)
    if matched:
        return InputCheck(Verdict.ESCALATE, "diagnosis_or_dose_request", matched)

    return InputCheck(Verdict.ALLOW, "in_scope")


def check_output(answer: str) -> bool:
    """Return ``True`` when an answer is safe to show to the patient."""
    return _matches(_normalize(answer), UNSAFE_OUTPUT_PATTERNS) is None


def sanitize_for_prompt(message: str, *, max_length: int = 1500) -> str:
    """Neutralise structural markers so patient text cannot forge prompt roles."""
    cleaned = message.strip()[:max_length]
    cleaned = re.sub(r"<\s*/?\s*(system|assistant|human|user)[^>]*>", " ", cleaned, flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip()
