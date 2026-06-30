from __future__ import annotations

import re
from datetime import date, datetime

CALL_DATE_FORMAT_PATTERN = re.compile(r"^\(\d{2},\d{2},\d{4}\)$")

_NUMERIC_DATE_PATTERNS = (
    re.compile(
        r"(?:as of today|views as of today|made as of today),?\s*"
        r"(\d{1,2}/\d{1,2}/(\d{4}))",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:as of today|views as of today|made as of today),?\s*"
        r"(\d{1,2})-(\d{1,2})-(\d{4})",
        re.IGNORECASE,
    ),
)

_NAMED_DATE_PATTERNS = (
    re.compile(
        r"(?:as of today|views as of today|made as of today),?\s*"
        r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})\s+Financial Results",
        re.IGNORECASE,
    ),
)

_NAMED_DATE_FORMATS = (
    "%B %d %Y",
    "%b %d %Y",
    "%B %d, %Y",
    "%b %d, %Y",
)


def format_call_date(value: date) -> str:
    return f"({value.month:02d},{value.day:02d},{value.year:04d})"


def is_valid_call_date_format(value: str) -> bool:
    return bool(CALL_DATE_FORMAT_PATTERN.match(value.strip()))


def parse_call_date_format(value: str) -> date | None:
    if not is_valid_call_date_format(value):
        return None
    month, day, year = value.strip()[1:-1].split(",")
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def _format_numeric_match(match: re.Match[str]) -> str | None:
    if match.group(1).count("/") == 2 or (
        "/" in match.group(1) and match.lastindex == 2
    ):
        month, day, year = match.group(1).split("/")
    else:
        month, day, year = match.group(1), match.group(2), match.group(3)
    try:
        return format_call_date(date(int(year), int(month), int(day)))
    except ValueError:
        return None


def _format_named_match(match: re.Match[str]) -> str | None:
    month_name = match.group(1)
    day = match.group(2)
    year = match.group(3)
    for fmt in _NAMED_DATE_FORMATS:
        try:
            parsed = datetime.strptime(f"{month_name} {day} {year}", fmt).date()
            return format_call_date(parsed)
        except ValueError:
            continue
    return None


def extract_call_date(transcript_text: str) -> str | None:
    """Extract the earnings call date from transcript text as (mm,dd,yyyy)."""
    search_text = transcript_text[:8000]
    for pattern in _NUMERIC_DATE_PATTERNS:
        match = pattern.search(search_text)
        if match:
            formatted = _format_numeric_match(match)
            if formatted:
                return formatted

    for pattern in _NAMED_DATE_PATTERNS:
        match = pattern.search(search_text)
        if match:
            formatted = _format_named_match(match)
            if formatted:
                return formatted
    return None


def resolve_call_date(transcript_text: str, llm_call_date: str | None = None) -> str | None:
    extracted = extract_call_date(transcript_text)
    if extracted:
        return extracted
    if llm_call_date and is_valid_call_date_format(llm_call_date):
        return llm_call_date.strip()
    return None


def resolve_call_date_value(transcript_text: str) -> date:
    from src.ingest.reported_quarter import ReportedQuarterError

    call_date_text = resolve_call_date(transcript_text)
    if not call_date_text:
        raise ReportedQuarterError(
            "Could not extract call date from transcript. "
            "Market data requires a call date in IR opening remarks."
        )
    parsed = parse_call_date_format(call_date_text)
    if parsed is None:
        raise ReportedQuarterError(f"Invalid call date format: {call_date_text!r}")
    return parsed
