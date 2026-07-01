from __future__ import annotations

import re
from pathlib import Path

from src.ingest.filings.types import FilingLoadError

QUARTER_PATTERN = re.compile(r"(?:FY)?(20\d{2})-Q([1-4])", re.IGNORECASE)


def parse_quarter_from_filename(path: Path) -> str | None:
    match = QUARTER_PATTERN.search(path.stem)
    if not match:
        return None
    year = match.group(1)
    quarter_num = match.group(2).upper()
    matched_text = match.group(0)
    if matched_text.upper().startswith("FY"):
        return f"FY{year}-Q{quarter_num}"
    return f"{year}-Q{quarter_num}"


def normalize_quarter_label(label: str) -> str:
    parsed = parse_quarter_from_filename(Path(label.strip()))
    if not parsed:
        raise FilingLoadError(
            "Invalid quarter label. Use FY2025-Q2 or 2025-Q2 format."
        )
    return parsed


def quarter_number(quarter: str) -> int:
    normalized = normalize_quarter_label(quarter)
    match = QUARTER_PATTERN.search(normalized)
    if not match:
        raise FilingLoadError(f"Invalid quarter label: {quarter}")
    return int(match.group(2))


def is_q4_quarter(quarter: str) -> bool:
    return quarter_number(quarter) == 4


def fiscal_year_prefix(quarter: str) -> str:
    normalized = normalize_quarter_label(quarter)
    match = QUARTER_PATTERN.search(normalized)
    if not match:
        raise FilingLoadError(f"Invalid quarter label: {quarter}")
    year = match.group(1)
    if normalized.upper().startswith("FY"):
        return f"FY{year}"
    return year


def sibling_quarter_label(fiscal_year_prefix_value: str, q_num: int) -> str:
    if fiscal_year_prefix_value.upper().startswith("FY"):
        year = fiscal_year_prefix_value[2:]
        return f"FY{year}-Q{q_num}"
    return f"{fiscal_year_prefix_value}-Q{q_num}"


def prior_quarter_labels_for_fy_q4(fiscal_year_prefix_value: str) -> list[str]:
    return [
        sibling_quarter_label(fiscal_year_prefix_value, q_num)
        for q_num in (1, 2, 3)
    ]


def quarter_sort_key(quarter: str) -> tuple[int, int, int]:
    normalized = normalize_quarter_label(quarter)
    match = QUARTER_PATTERN.search(normalized)
    if not match:
        raise FilingLoadError(f"Invalid quarter label: {quarter}")
    fiscal_prefix = 1 if normalized.upper().startswith("FY") else 0
    return (int(match.group(1)), int(match.group(2)), fiscal_prefix)


def parse_quarters_list(value: str) -> list[str]:
    parts = [item.strip() for item in value.split(",") if item.strip()]
    if not parts:
        raise FilingLoadError("--quarter must list at least one quarter label.")
    normalized = [normalize_quarter_label(part) for part in parts]
    return sorted(dict.fromkeys(normalized), key=quarter_sort_key)
