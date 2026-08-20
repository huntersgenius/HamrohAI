"""Phone number normalisation.

The phone number is the single identity key of the whole platform (spec 2.1), so
every entry point must normalise it exactly the same way before it touches the
database. Everything is stored in E.164.
"""

from __future__ import annotations

import phonenumbers

from app.core.errors import ValidationError

DEFAULT_REGION = "UZ"


def normalize_phone(raw: str, region: str = DEFAULT_REGION) -> str:
    """Return the E.164 form (``+998901234567``) or raise ``ValidationError``."""
    if not raw or not raw.strip():
        raise ValidationError("phone number is required", code="phone_required")
    candidate = raw.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    try:
        parsed = phonenumbers.parse(candidate, None if candidate.startswith("+") else region)
    except phonenumbers.NumberParseException as exc:
        raise ValidationError("invalid phone number", code="phone_invalid") from exc
    if not phonenumbers.is_valid_number(parsed):
        raise ValidationError("invalid phone number", code="phone_invalid")
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def mask_phone(e164: str) -> str:
    """``+998901234567`` -> ``+998 ** *** 45 67`` for display in shared contexts."""
    if len(e164) < 6:
        return "***"
    return f"{e164[:4]} ** *** {e164[-4:-2]} {e164[-2:]}"
