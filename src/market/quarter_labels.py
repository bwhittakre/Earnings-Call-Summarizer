from __future__ import annotations

import re
from datetime import date

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


def latest_completed_calendar_quarter(*, today: date | None = None) -> str:
    today = today or date.today()
    current_q = (today.month - 1) // 3 + 1
    year = today.year
    completed_q = current_q - 1
    if completed_q < 1:
        completed_q = 4
        year -= 1
    return format_quarter_label(False, year, completed_q)


def fiscal_quarter_labels_back(
    count: int,
    *,
    end_label: str | None = None,
) -> list[str]:
    end = normalize_quarter_label(end_label or latest_completed_calendar_quarter())
    is_fiscal, year, quarter_num = parse_quarter_label(end)
    if not is_fiscal:
        end = format_quarter_label(True, year, quarter_num)
        is_fiscal, year, quarter_num = parse_quarter_label(end)
    labels: list[str] = []
    q = quarter_num
    y = year
    for _ in range(count):
        labels.append(format_quarter_label(True, y, q))
        q -= 1
        if q < 1:
            q = 4
            y -= 1
    labels.reverse()
    return labels


def batch_quarter_labels_for_ticker(
    ticker: str,
    count: int,
    *,
    end_label: str | None = None,
    calendars_path=None,
) -> list[str]:
    from pathlib import Path

    from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH, load_fiscal_calendars

    path = calendars_path or DEFAULT_FISCAL_CALENDARS_PATH
    ticker_key = ticker.strip().upper()
    config = load_fiscal_calendars(path)
    calendar_type = config.get(ticker_key, {}).get("type", "calendar_fiscal")

    resolved_end = end_label
    if resolved_end is not None:
        normalized = normalize_quarter_label(resolved_end)
        is_fiscal, year, quarter_num = parse_quarter_label(normalized)
        if calendar_type == "nvidia_fiscal" and not is_fiscal:
            resolved_end = format_quarter_label(True, year, quarter_num)

    if calendar_type == "nvidia_fiscal":
        return fiscal_quarter_labels_back(count, end_label=resolved_end)
    return calendar_quarter_labels_back(count, end_label=resolved_end)


def calendar_quarter_labels_back(
    count: int,
    *,
    end_label: str | None = None,
) -> list[str]:
    end = normalize_quarter_label(end_label or latest_completed_calendar_quarter())
    is_fiscal, year, quarter_num = parse_quarter_label(end)
    if is_fiscal:
        raise ValueError("calendar_quarter_labels_back requires calendar quarter labels")
    labels: list[str] = []
    q = quarter_num
    y = year
    for _ in range(count):
        labels.append(format_quarter_label(False, y, q))
        q -= 1
        if q < 1:
            q = 4
            y -= 1
    labels.reverse()
    return labels


def quarter_sort_key(label: str) -> tuple[int, int]:
    _, year, quarter_num = parse_quarter_label(label)
    return year, quarter_num
