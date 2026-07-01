from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from src.ingest.filings.fiscal import normalize_quarter_label

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


def prior_quarter_label(current: str) -> str:
    return prior_quarter_labels(current, count=1)[0]


def prior_quarter_labels_for_price_lookup(
    reported_quarter: str,
    as_of_date: date,
    ticker: str,
    *,
    calendars_path: Path,
    overrides: dict[str, date] | None = None,
    count: int = 4,
) -> list[str]:
    """Return up to ``count`` prior quarter labels whose fiscal quarter-ends are on or before ``as_of_date``.

    Walks backward one quarter at a time so price history stays chronological even when
    ``prior_quarter_labels(reported)`` would span a full prior fiscal year (e.g. FY2026-Q1).
    """
    from src.market.fiscal_calendar import resolve_quarter_end_date

    if not isinstance(as_of_date, date):
        raise TypeError("as_of_date must be a date")

    selected: list[str] = []
    cursor = reported_quarter
    for _ in range(count * 8):
        if len(selected) >= count:
            break
        prior = prior_quarter_label(cursor)
        quarter_end = resolve_quarter_end_date(
            ticker,
            prior,
            calendars_path=calendars_path,
            overrides=overrides,
        )
        if quarter_end <= as_of_date:
            selected.append(prior)
        cursor = prior

    if len(selected) < count:
        raise ValueError(
            f"Could not resolve {count} prior quarters on or before "
            f"{as_of_date.isoformat()} for {reported_quarter!r}."
        )

    selected.reverse()
    return selected
