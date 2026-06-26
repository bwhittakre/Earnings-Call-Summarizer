from __future__ import annotations

import re

from src.ingest.loader import normalize_quarter_label

_QUARTER_LABEL_PATTERN = re.compile(r"^(FY)?(\d{4})-Q([1-4])$", re.IGNORECASE)


def parse_quarter_label(label: str) -> tuple[bool, int, int]:
    normalized = normalize_quarter_label(label)
    match = _QUARTER_LABEL_PATTERN.match(normalized)
    if not match:
        raise ValueError(f"Invalid quarter label: {label}")
    is_fiscal = bool(match.group(1))
    year = int(match.group(2))
    quarter_num = int(match.group(3))
    return is_fiscal, year, quarter_num


def format_quarter_label(is_fiscal: bool, year: int, quarter_num: int) -> str:
    prefix = "FY" if is_fiscal else ""
    return f"{prefix}{year}-Q{quarter_num}"


def prior_quarter_labels(current: str, count: int = 4) -> list[str]:
    is_fiscal, year, quarter_num = parse_quarter_label(current)
    labels: list[str] = []
    q = quarter_num
    y = year
    for _ in range(count):
        q -= 1
        if q < 1:
            q = 4
            y -= 1
        labels.append(format_quarter_label(is_fiscal, y, q))
    labels.reverse()
    return labels
