from __future__ import annotations

import calendar
from datetime import date, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from src.ingest.filings.fiscal import fiscal_year_prefix, normalize_quarter_label
from src.market.quarter_labels import parse_quarter_label

if TYPE_CHECKING:
    from src.ingest.edgar.fiscal_profile import FiscalProfile

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


def _calendar_fiscal_quarter_end(fiscal_year: int, quarter_num: int) -> date:
    calendar_year = fiscal_year - 1
    month, day = _CALENDAR_QUARTER_END_MONTHS[quarter_num]
    return date(calendar_year, month, day)


def _nvidia_fiscal_quarter_end(fiscal_year: int, quarter_num: int) -> date:
    if quarter_num == 4:
        return _last_sunday_of_month(fiscal_year, _NVIDIA_QUARTER_END_MONTHS[4])
    return _last_sunday_of_month(fiscal_year - 1, _NVIDIA_QUARTER_END_MONTHS[quarter_num])


def _safe_fye_date(year: int, month: int, day: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day, last_day))


def _subtract_months(day: date, months: int) -> date:
    year = day.year
    month = day.month - months
    while month <= 0:
        month += 12
        year -= 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, last_day)


def _last_day_of_month(day: date) -> date:
    last_day = calendar.monthrange(day.year, day.month)[1]
    return date(day.year, day.month, last_day)


def _offset_fiscal_quarter_end(
    fiscal_year: int,
    quarter_num: int,
    *,
    fye_month: int,
    fye_day: int,
) -> date:
    q4_end = _safe_fye_date(fiscal_year, fye_month, fye_day)
    months_before_q4 = (4 - quarter_num) * 3
    target = _subtract_months(q4_end, months_before_q4)
    return _last_day_of_month(target)


def _resolve_from_profile(
    profile: FiscalProfile,
    normalized_label: str,
) -> date | None:
    explicit = profile.quarter_ends.get(normalized_label)
    if explicit:
        return date.fromisoformat(explicit)

    _, fiscal_year, quarter_num = parse_quarter_label(normalized_label)
    if profile.calendar_type == "calendar_fiscal":
        return _calendar_fiscal_quarter_end(fiscal_year, quarter_num)
    if profile.calendar_type == "nvidia_fiscal":
        return _nvidia_fiscal_quarter_end(fiscal_year, quarter_num)
    if profile.calendar_type == "offset_fiscal":
        return _offset_fiscal_quarter_end(
            fiscal_year,
            quarter_num,
            fye_month=profile.fye_month,
            fye_day=profile.fye_day,
        )
    return None


def resolve_quarter_end_date(
    ticker: str,
    quarter_label: str,
    *,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    overrides: dict[str, date] | None = None,
    fiscal_profile: FiscalProfile | None = None,
) -> date:
    normalized_label = normalize_quarter_label(quarter_label)
    if overrides and normalized_label in overrides:
        return overrides[normalized_label]

    if fiscal_profile is not None:
        resolved = _resolve_from_profile(fiscal_profile, normalized_label)
        if resolved is not None:
            return resolved

    from src.market.fiscal_calendar import load_fiscal_calendars

    config = load_fiscal_calendars(calendars_path)
    ticker_key = ticker.strip().upper()
    if ticker_key not in config:
        if fiscal_profile is None:
            from src.ingest.edgar.fiscal_profile import load_cached_fiscal_profile

            fiscal_profile = load_cached_fiscal_profile(ticker_key)
        if fiscal_profile is not None:
            resolved = _resolve_from_profile(fiscal_profile, normalized_label)
            if resolved is not None:
                return resolved
        raise FiscalCalendarError(
            f"No fiscal calendar configured for ticker {ticker_key!r}. "
            f"Add it to {calendars_path}, pass --quarter-end-dates, "
            f"or run with --fetch-missing to bootstrap from SEC data."
        )

    entry = config[ticker_key]
    explicit = entry.get("overrides", {})
    if normalized_label in explicit:
        return date.fromisoformat(str(explicit[normalized_label]))

    calendar_type = entry.get("type")
    _, fiscal_year, quarter_num = parse_quarter_label(normalized_label)
    if calendar_type == "calendar_fiscal":
        return _calendar_fiscal_quarter_end(fiscal_year, quarter_num)
    if calendar_type == "nvidia_fiscal":
        return _nvidia_fiscal_quarter_end(fiscal_year, quarter_num)

    raise FiscalCalendarError(
        f"Unsupported fiscal calendar type {calendar_type!r} for ticker {ticker_key!r}."
    )


def resolve_quarter_end_dates(
    ticker: str,
    quarter_labels: list[str],
    *,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    overrides: dict[str, date] | None = None,
    fiscal_profile: FiscalProfile | None = None,
) -> dict[str, date]:
    return {
        normalize_quarter_label(label): resolve_quarter_end_date(
            ticker,
            label,
            calendars_path=calendars_path,
            overrides=overrides,
            fiscal_profile=fiscal_profile,
        )
        for label in quarter_labels
    }


def expected_period_end_date(
    ticker: str,
    quarter: str,
    *,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    fiscal_profile: FiscalProfile | None = None,
) -> date:
    return resolve_quarter_end_date(
        ticker,
        quarter,
        calendars_path=calendars_path,
        fiscal_profile=fiscal_profile,
    )


def manifest_as_of_date_text(
    ticker: str,
    quarter: str,
    *,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    fiscal_profile: FiscalProfile | None = None,
) -> str:
    end = expected_period_end_date(
        ticker,
        quarter,
        calendars_path=calendars_path,
        fiscal_profile=fiscal_profile,
    )
    return f"({end.month:02d},{end.day:02d},{end.year})"


def fiscal_year_end_date(
    ticker: str,
    quarter: str,
    *,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    fiscal_profile: FiscalProfile | None = None,
) -> date:
    normalized = normalize_quarter_label(quarter)
    return expected_period_end_date(
        ticker,
        f"{fiscal_year_prefix(normalized)}-Q4",
        calendars_path=calendars_path,
        fiscal_profile=fiscal_profile,
    )
