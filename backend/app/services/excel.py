"""Excel export/import for trend charts (spec 4.2 tab 1, 5.2 tab 2).

The doctor can export *and* import; the patient can only export. Import is how a
doctor backfills readings taken on paper or on a clinic device, so it must be
forgiving about formats a real clinic produces (Excel dates, comma decimals,
"120/80" typed into one cell) while refusing anything ambiguous.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.core.errors import ValidationError
from app.models.care import MetricReading, MetricSeries
from app.services.medications import UZ_TZ

HEADER_FILL = PatternFill("solid", fgColor="1F6F5C")
HEADER_FONT = Font(color="FFFFFF", bold=True)
OUT_OF_RANGE_FILL = PatternFill("solid", fgColor="FDE2E1")

_COLUMNS_UZ = ["Sana", "Vaqt", "Qiymat", "Ikkinchi qiymat", "Birlik", "Izoh"]
_COLUMNS_RU = ["Дата", "Время", "Значение", "Второе значение", "Единица", "Примечание"]
_COLUMNS_EN = ["Date", "Time", "Value", "Secondary value", "Unit", "Note"]

_HEADER_ALIASES = {
    "date": {"sana", "дата", "date"},
    "time": {"vaqt", "время", "time"},
    "value": {"qiymat", "значение", "value", "systolic", "sistolik", "систолическое"},
    "value_secondary": {
        "ikkinchi qiymat",
        "второе значение",
        "secondary value",
        "diastolic",
        "diastolik",
        "диастолическое",
    },
    "note": {"izoh", "примечание", "note", "comment"},
}


def _columns(locale: str) -> list[str]:
    return {"ru": _COLUMNS_RU, "en": _COLUMNS_EN}.get(locale, _COLUMNS_UZ)


def export_series(
    series: MetricSeries, readings: list[MetricReading], *, locale: str = "uz"
) -> bytes:
    """Render one trend chart as a formatted .xlsx workbook."""
    workbook = Workbook()
    sheet = workbook.active
    label = (series.label or {}).get(locale) or (series.label or {}).get("uz") or series.key
    # Excel sheet titles cannot exceed 31 chars or contain []:*?/\
    sheet.title = re.sub(r"[\[\]:*?/\\]", " ", label)[:31] or "Data"

    headers = _columns(locale)
    sheet.append(headers)
    for index in range(1, len(headers) + 1):
        cell = sheet.cell(row=1, column=index)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")

    for reading in sorted(readings, key=lambda r: r.recorded_at):
        local_dt = (
            reading.recorded_at
            if reading.recorded_at.tzinfo
            else reading.recorded_at.replace(tzinfo=UTC)
        ).astimezone(UZ_TZ)
        sheet.append(
            [
                local_dt.strftime("%Y-%m-%d"),
                local_dt.strftime("%H:%M"),
                reading.value,
                reading.value_secondary,
                series.unit,
                reading.note or "",
            ]
        )
        # Readings outside the doctor's target range are highlighted so the
        # exported file is readable on paper without opening the app.
        if _out_of_range(series, reading.value):
            for index in range(1, len(headers) + 1):
                sheet.cell(row=sheet.max_row, column=index).fill = OUT_OF_RANGE_FILL

    for index, width in enumerate([14, 10, 14, 18, 12, 40], start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _out_of_range(series: MetricSeries, value: float) -> bool:
    if series.target_min is not None and value < series.target_min:
        return True
    return series.target_max is not None and value > series.target_max


@dataclass(slots=True)
class ImportedRow:
    recorded_at: datetime
    value: float
    value_secondary: float | None = None
    note: str | None = None


@dataclass(slots=True)
class ImportResult:
    rows: list[ImportedRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped: int = 0


def parse_series_workbook(data: bytes, *, max_rows: int = 5000) -> ImportResult:
    """Parse an uploaded workbook into readings.

    Returns partial results with per-row errors rather than failing the whole
    file: one malformed row in a year of records should not block the import.
    """
    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - openpyxl raises many unrelated types
        raise ValidationError("cannot read the Excel file", code="excel_unreadable") from exc

    sheet = workbook.active
    if sheet is None:
        raise ValidationError("workbook has no sheets", code="excel_empty")

    result = ImportResult()
    header_map: dict[str, int] | None = None

    for row_index, raw_row in enumerate(sheet.iter_rows(values_only=True), start=1):
        if row_index > max_rows + 1:
            result.errors.append(f"row limit {max_rows} exceeded, remaining rows ignored")
            break
        if raw_row is None or all(cell is None or cell == "" for cell in raw_row):
            continue

        if header_map is None:
            header_map = _detect_header(raw_row)
            if header_map is not None:
                continue
            # No recognisable header: assume the canonical column order.
            header_map = {"date": 0, "time": 1, "value": 2, "value_secondary": 3, "note": 5}

        try:
            parsed = _parse_row(raw_row, header_map)
        except ValueError as exc:
            result.skipped += 1
            result.errors.append(f"row {row_index}: {exc}")
            continue
        if parsed is not None:
            result.rows.append(parsed)

    workbook.close()
    if not result.rows and not result.errors:
        raise ValidationError("no readings found in the file", code="excel_no_rows")
    return result


def _detect_header(row: tuple) -> dict[str, int] | None:
    mapping: dict[str, int] = {}
    for index, cell in enumerate(row):
        if not isinstance(cell, str):
            continue
        normalized = cell.strip().lower()
        for field_name, aliases in _HEADER_ALIASES.items():
            if normalized in aliases:
                mapping[field_name] = index
    return mapping if "value" in mapping and "date" in mapping else None


def _parse_row(row: tuple, header: dict[str, int]) -> ImportedRow | None:
    def cell(name: str):
        index = header.get(name)
        if index is None or index >= len(row):
            return None
        return row[index]

    raw_value = cell("value")
    if raw_value is None or raw_value == "":
        return None

    secondary = _to_float(cell("value_secondary"))
    # A clinic often types blood pressure as a single "120/80" cell.
    if isinstance(raw_value, str) and "/" in raw_value:
        left, _, right = raw_value.partition("/")
        value = _to_float(left)
        secondary = secondary if secondary is not None else _to_float(right)
    else:
        value = _to_float(raw_value)

    if value is None:
        raise ValueError(f"unreadable value '{raw_value}'")

    recorded_at = _parse_datetime(cell("date"), cell("time"))
    note = cell("note")
    return ImportedRow(
        recorded_at=recorded_at,
        value=value,
        value_secondary=secondary,
        note=str(note).strip()[:1000] if note else None,
    )


def _to_float(value) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(match.group()) if match else None


def _parse_datetime(raw_date, raw_time) -> datetime:
    """Combine the date and time cells into an aware UTC timestamp."""
    if raw_date is None:
        raise ValueError("missing date")

    if isinstance(raw_date, datetime):
        base = raw_date
    elif isinstance(raw_date, date):
        base = datetime.combine(raw_date, datetime.min.time())
    else:
        base = _parse_date_string(str(raw_date).strip())

    hour, minute = base.hour, base.minute
    if raw_time is not None and not isinstance(raw_date, datetime):
        hour, minute = _parse_time_cell(raw_time, hour, minute)

    local = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if local.tzinfo is None:
        local = local.replace(tzinfo=UZ_TZ)
    return local.astimezone(UTC)


def _parse_date_string(text: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text.split(" ")[0], fmt)
        except ValueError:
            continue
    raise ValueError(f"unrecognised date '{text}'")


def _parse_time_cell(raw_time, default_hour: int, default_minute: int) -> tuple[int, int]:
    if isinstance(raw_time, datetime):
        return raw_time.hour, raw_time.minute
    if hasattr(raw_time, "hour") and hasattr(raw_time, "minute"):
        return int(raw_time.hour), int(raw_time.minute)
    match = re.match(r"^(\d{1,2}):(\d{2})", str(raw_time).strip())
    if not match:
        return default_hour, default_minute
    hour, minute = int(match.group(1)), int(match.group(2))
    if 0 <= hour <= 23 and 0 <= minute <= 59:
        return hour, minute
    return default_hour, default_minute
