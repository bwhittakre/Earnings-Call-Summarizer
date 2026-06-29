from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from src.ingest.loader import normalize_quarter_label
from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH, resolve_quarter_end_date
from src.market.quarter_labels import parse_quarter_label


@dataclass
class QuarterAllocation:
    quarter_label: str
    quarter_num: int
    quarter_end: date
    earnings_window_start: date
    earnings_window_end: date
    needs_ten_q: bool
    needs_ten_k_primary: bool
    needs_ten_k_context: bool


def allocate_quarter(
    ticker: str,
    quarter_label: str,
    *,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    date_overrides: dict[str, date] | None = None,
    earnings_window_days: int = 75,
) -> QuarterAllocation:
    normalized = normalize_quarter_label(quarter_label)
    _, _, quarter_num = parse_quarter_label(normalized)
    quarter_end = resolve_quarter_end_date(
        ticker,
        normalized,
        calendars_path=calendars_path,
        overrides=date_overrides,
    )
    window_start = quarter_end
    window_end = quarter_end + timedelta(days=earnings_window_days)
    return QuarterAllocation(
        quarter_label=normalized,
        quarter_num=quarter_num,
        quarter_end=quarter_end,
        earnings_window_start=window_start,
        earnings_window_end=window_end,
        needs_ten_q=quarter_num in {1, 2, 3},
        needs_ten_k_primary=quarter_num == 4,
        needs_ten_k_context=quarter_num in {1, 2, 3},
    )
