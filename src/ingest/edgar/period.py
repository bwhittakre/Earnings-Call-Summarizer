from __future__ import annotations

import calendar
from datetime import date, timedelta

from src.ingest.filings.fiscal import fiscal_year_prefix, normalize_quarter_label
from src.market.fiscal_calendar import (
    DEFAULT_FISCAL_CALENDARS_PATH,
    load_fiscal_calendars,
)
from src.market.quarter_labels import parse_quarter_label


def _last_sunday_on_or_before(day: date) -> date:
    cursor = day
    while cursor.weekday() != 6:
        cursor -= timedelta(days=1)
    return cursor


def _last_sunday_of_month(year: int, month: int) -> date:
    last_day = calendar.monthrange(year, month)[1]
    return _last_sunday_on_or_before(date(year, month, last_day))


def _calendar_quarter_end(year: int, quarter_num: int) -> date:
    month_day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}
    month, day = month_day[quarter_num]
    return date(year, month, day)


def _nvidia_quarter_end(fiscal_year: int, quarter_num: int) -> date:
    month_map = {1: 4, 2: 7, 3: 10, 4: 1}
    if quarter_num == 4:
        return _last_sunday_of_month(fiscal_year, month_map[4])
    return _last_sunday_of_month(fiscal_year - 1, month_map[quarter_num])


def expected_period_end_date(
    ticker: str,
    quarter: str,
    *,
    calendars_path=DEFAULT_FISCAL_CALENDARS_PATH,
) -> date:
    normalized = normalize_quarter_label(quarter)
    _, fiscal_year, quarter_num = parse_quarter_label(normalized)
    config = load_fiscal_calendars(calendars_path)
    ticker_key = ticker.strip().upper()
    if ticker_key not in config:
        raise ValueError(f"No fiscal calendar configured for {ticker_key!r}.")

    calendar_type = config[ticker_key].get("type")
    if calendar_type == "calendar_fiscal":
        # Match AMZN manifest convention: quarter ends fall in calendar year FY-1.
        calendar_year = fiscal_year - 1
        return _calendar_quarter_end(calendar_year, quarter_num)
    if calendar_type == "nvidia_fiscal":
        return _nvidia_quarter_end(fiscal_year, quarter_num)
    raise ValueError(f"Unsupported fiscal calendar type {calendar_type!r}.")


def manifest_as_of_date_text(ticker: str, quarter: str) -> str:
    end = expected_period_end_date(ticker, quarter)
    return f"({end.month:02d},{end.day:02d},{end.year})"


def fiscal_year_end_date(ticker: str, quarter: str) -> date:
    normalized = normalize_quarter_label(quarter)
    return expected_period_end_date(ticker, f"{fiscal_year_prefix(normalized)}-Q4")
