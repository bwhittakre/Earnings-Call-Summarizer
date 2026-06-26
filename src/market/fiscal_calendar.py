from __future__ import annotations

import calendar
from datetime import date, timedelta
from pathlib import Path

import yaml

from src.ingest.loader import normalize_quarter_label
from src.market.quarter_labels import parse_quarter_label

DEFAULT_FISCAL_CALENDARS_PATH = (
    Path(__file__).resolve().parent.parent.parent / "config" / "fiscal_calendars.yaml"
)

_CALENDAR_QUARTER_END_MONTHS = {
    1: (3, 31),
    2: (6, 30),
    3: (9, 30),
    4: (12, 31),
}

_NVIDIA_QUARTER_END_MONTHS = {
    1: 4,
    2: 7,
    3: 10,
    4: 1,
}


class FiscalCalendarError(Exception):
    pass


def _last_sunday_on_or_before(day: date) -> date:
    cursor = day
    while cursor.weekday() != 6:
        cursor -= timedelta(days=1)
    return cursor


def _last_sunday_of_month(year: int, month: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return _last_sunday_on_or_before(date(year, month, last_day))


def _calendar_fiscal_quarter_end(year: int, quarter_num: int) -> date:
    month, day = _CALENDAR_QUARTER_END_MONTHS[quarter_num]
    return date(year, month, day)


def _nvidia_fiscal_quarter_end(year: int, quarter_num: int) -> date:
    if quarter_num == 4:
        return _last_sunday_of_month(year, _NVIDIA_QUARTER_END_MONTHS[4])
    return _last_sunday_of_month(year - 1, _NVIDIA_QUARTER_END_MONTHS[quarter_num])


def load_fiscal_calendars(path: Path = DEFAULT_FISCAL_CALENDARS_PATH) -> dict:
    if not path.exists():
        raise FiscalCalendarError(f"Fiscal calendar config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FiscalCalendarError(f"Invalid fiscal calendar config: {path}")
    return data


def resolve_quarter_end_date(
    ticker: str,
    quarter_label: str,
    *,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    overrides: dict[str, date] | None = None,
) -> date:
    normalized_label = normalize_quarter_label(quarter_label)
    if overrides and normalized_label in overrides:
        return overrides[normalized_label]

    config = load_fiscal_calendars(calendars_path)
    ticker_key = ticker.strip().upper()
    if ticker_key not in config:
        raise FiscalCalendarError(
            f"No fiscal calendar configured for ticker {ticker_key!r}. "
            f"Add it to {calendars_path} or pass --quarter-end-dates."
        )

    entry = config[ticker_key]
    explicit = entry.get("overrides", {})
    if normalized_label in explicit:
        return date.fromisoformat(str(explicit[normalized_label]))

    calendar_type = entry.get("type")
    is_fiscal, year, quarter_num = parse_quarter_label(normalized_label)
    if calendar_type == "calendar_fiscal":
        if is_fiscal:
            return _calendar_fiscal_quarter_end(year, quarter_num)
        return _calendar_fiscal_quarter_end(year, quarter_num)
    if calendar_type == "nvidia_fiscal":
        if not is_fiscal:
            raise FiscalCalendarError(
                f"Ticker {ticker_key} requires FY####-Q# labels, got {normalized_label!r}."
            )
        return _nvidia_fiscal_quarter_end(year, quarter_num)

    raise FiscalCalendarError(
        f"Unsupported fiscal calendar type {calendar_type!r} for ticker {ticker_key!r}."
    )


def resolve_quarter_end_dates(
    ticker: str,
    quarter_labels: list[str],
    *,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    overrides: dict[str, date] | None = None,
) -> dict[str, date]:
    return {
        normalize_quarter_label(label): resolve_quarter_end_date(
            ticker,
            label,
            calendars_path=calendars_path,
            overrides=overrides,
        )
        for label in quarter_labels
    }


def parse_quarter_end_dates_override(value: str) -> dict[str, date]:
    if not value.strip():
        return {}
    parsed: dict[str, date] = {}
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise FiscalCalendarError(
                "Invalid --quarter-end-dates format. Use FY2025-Q2:2024-07-28,..."
            )
        label, date_text = part.split(":", 1)
        parsed[normalize_quarter_label(label.strip())] = date.fromisoformat(
            date_text.strip()
        )
    return parsed
