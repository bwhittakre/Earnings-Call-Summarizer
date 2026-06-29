from __future__ import annotations

import re

from src.ingest.loader import normalize_quarter_label

SEARCH_WINDOW = 3000

_SPOKEN_QUARTER_NUMBERS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
}


class ReportedQuarterError(Exception):
    pass


def _format_label(is_fiscal: bool, year: int, quarter_num: int) -> str:
    prefix = "FY" if is_fiscal else ""
    return normalize_quarter_label(f"{prefix}{year}-Q{quarter_num}")


def extract_reported_quarter(transcript_text: str) -> str | None:
    search_text = transcript_text[:SEARCH_WINDOW]

    match = re.search(
        r"\b(first|second|third|fourth)\s+quarter\s+of\s+fiscal\s+(20\d{2})\b",
        search_text,
        re.IGNORECASE,
    )
    if match:
        quarter_num = _SPOKEN_QUARTER_NUMBERS[match.group(1).lower()]
        return _format_label(True, int(match.group(2)), quarter_num)

    match = re.search(
        r"\b(?:our\s+)?Q([1-4])\s+(20\d{2})\s+financial\s+results\b",
        search_text,
        re.IGNORECASE,
    )
    if match:
        return _format_label(False, int(match.group(2)), int(match.group(1)))

    match = re.search(
        r"\bQ([1-4])\s+(FY)?(20\d{2})\b",
        search_text,
        re.IGNORECASE,
    )
    if match:
        return _format_label(bool(match.group(2)), int(match.group(3)), int(match.group(1)))

    match = re.search(
        r"\b(FY)?(20\d{2})[- ]Q([1-4])\b",
        search_text,
        re.IGNORECASE,
    )
    if match:
        return _format_label(bool(match.group(1)), int(match.group(2)), int(match.group(3)))

    match = re.search(
        r"\b(first|second|third|fourth)\s+quarter\s+of\s+(20\d{2})\b",
        search_text,
        re.IGNORECASE,
    )
    if match:
        quarter_num = _SPOKEN_QUARTER_NUMBERS[match.group(1).lower()]
        return _format_label(False, int(match.group(2)), quarter_num)

    return None


def resolve_reported_quarter(
    transcript_text: str,
    *,
    cli_override: str | None = None,
) -> str:
    if cli_override:
        return normalize_quarter_label(cli_override)

    extracted = extract_reported_quarter(transcript_text)
    if extracted:
        return extracted

    raise ReportedQuarterError(
        "Could not extract reported quarter from transcript opening. "
        "Pass --reported-quarter (e.g. 2025-Q4 or FY2025-Q4)."
    )
