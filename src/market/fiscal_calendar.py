from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from src.market.fiscal_resolver import (
    DEFAULT_FISCAL_CALENDARS_PATH,
    FiscalCalendarError,
    resolve_quarter_end_date,
    resolve_quarter_end_dates,
)

__all__ = [
    "DEFAULT_FISCAL_CALENDARS_PATH",
    "FiscalCalendarError",
    "load_fiscal_calendars",
    "parse_quarter_end_dates_override",
    "resolve_quarter_end_date",
    "resolve_quarter_end_dates",
]


def load_fiscal_calendars(path: Path = DEFAULT_FISCAL_CALENDARS_PATH) -> dict:
    if not path.exists():
        raise FiscalCalendarError(f"Fiscal calendar config not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FiscalCalendarError(f"Invalid fiscal calendar config: {path}")
    return data


def parse_quarter_end_dates_override(value: str) -> dict[str, date]:
    from src.ingest.filings.fiscal import normalize_quarter_label

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
