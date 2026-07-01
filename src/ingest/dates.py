from __future__ import annotations

import re
from datetime import date

AS_OF_DATE_FORMAT_PATTERN = re.compile(r"^\(\d{2},\d{2},\d{4}\)$")


def format_as_of_date(value: date) -> str:
    return f"({value.month:02d},{value.day:02d},{value.year:04d})"


def is_valid_as_of_date_format(value: str) -> bool:
    return bool(AS_OF_DATE_FORMAT_PATTERN.match(value.strip()))


def parse_as_of_date_format(value: str) -> date | None:
    if not is_valid_as_of_date_format(value):
        return None
    month, day, year = value.strip()[1:-1].split(",")
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def resolve_as_of_date_text(
    manifest_value: str | None,
    llm_value: str | None = None,
) -> str | None:
    if manifest_value and is_valid_as_of_date_format(manifest_value):
        return manifest_value.strip()
    if llm_value and is_valid_as_of_date_format(llm_value):
        return llm_value.strip()
    return None


def resolve_as_of_date_value(
    manifest_value: str | None,
    *,
    required: bool = False,
    llm_value: str | None = None,
) -> date | None:
    text = resolve_as_of_date_text(manifest_value, llm_value)
    if text is None:
        if required:
            raise ValueError(
                "as_of_date is required (set manifest.json as_of_date as (mm,dd,yyyy))."
            )
        return None
    parsed = parse_as_of_date_format(text)
    if parsed is None:
        raise ValueError(f"Invalid as_of_date format: {text!r}")
    return parsed
