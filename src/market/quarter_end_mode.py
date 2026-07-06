from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TYPE_CHECKING

from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH, FiscalCalendarError
from src.market.fiscal_resolver import resolve_quarter_end_date
from src.market.quarter_labels import format_quarter_label

if TYPE_CHECKING:
    from src.ingest.edgar.fiscal_profile import FiscalProfile


class QuarterEndModeError(FiscalCalendarError):
    pass


@dataclass(frozen=True)
class QuarterEndRun:
    anchor_date: date
    company_quarters: dict[str, str]

    def date_overrides(self) -> dict[str, date]:
        return {
            quarter: self.anchor_date for quarter in self.company_quarters.values()
        }


def parse_quarter_end_anchor(value: str) -> date:
    text = value.strip()
    if not text:
        raise QuarterEndModeError("Quarter-end date cannot be empty.")
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise QuarterEndModeError(
            f"Invalid quarter-end date {value!r}. Use ISO format YYYY-MM-DD (e.g. 2025-06-30)."
        ) from exc


def resolve_quarter_label_for_date(
    ticker: str,
    target_date: date,
    *,
    calendars_path=DEFAULT_FISCAL_CALENDARS_PATH,
    fiscal_profile: FiscalProfile | None = None,
    tolerance_days: int = 5,
    max_nearest_days: int = 45,
) -> str:
    ticker_key = ticker.strip().upper()
    if fiscal_profile is None:
        from src.ingest.edgar.fiscal_profile import load_cached_fiscal_profile

        fiscal_profile = load_cached_fiscal_profile(ticker_key)

    strict_label: str | None = None
    strict_delta = tolerance_days + 1
    nearest_label: str | None = None
    nearest_delta = max_nearest_days + 1

    def _consider(label: str, end: date) -> None:
        nonlocal strict_label, strict_delta, nearest_label, nearest_delta
        delta = abs((end - target_date).days)
        if delta <= tolerance_days and delta < strict_delta:
            strict_label = label
            strict_delta = delta
        if delta <= max_nearest_days and delta < nearest_delta:
            nearest_label = label
            nearest_delta = delta

    if fiscal_profile is not None:
        for label, iso_text in fiscal_profile.quarter_ends.items():
            _consider(label, date.fromisoformat(iso_text))

    for fiscal_year in range(target_date.year - 1, target_date.year + 3):
        for quarter_num in range(1, 5):
            label = format_quarter_label(True, fiscal_year, quarter_num)
            try:
                end = resolve_quarter_end_date(
                    ticker_key,
                    label,
                    calendars_path=calendars_path,
                    fiscal_profile=fiscal_profile,
                )
            except FiscalCalendarError:
                continue
            _consider(label, end)

    if strict_label is not None:
        return strict_label
    if nearest_label is not None:
        return nearest_label

    raise QuarterEndModeError(
        f"No fiscal quarter label within {max_nearest_days} days of "
        f"{target_date.isoformat()} for {ticker_key!r}."
    )


def build_quarter_end_run(
    tickers: list[str],
    anchor_date: date,
    *,
    calendars_path=DEFAULT_FISCAL_CALENDARS_PATH,
    fiscal_profiles: dict[str, FiscalProfile] | None = None,
    tolerance_days: int = 5,
) -> QuarterEndRun:
    profiles = fiscal_profiles or {}
    company_quarters: dict[str, str] = {}
    for ticker in tickers:
        ticker_key = ticker.strip().upper()
        company_quarters[ticker_key] = resolve_quarter_label_for_date(
            ticker_key,
            anchor_date,
            calendars_path=calendars_path,
            fiscal_profile=profiles.get(ticker_key),
            tolerance_days=tolerance_days,
        )
    return QuarterEndRun(anchor_date=anchor_date, company_quarters=company_quarters)


def format_quarter_end_resolution(run: QuarterEndRun) -> str:
    lines = [f"Quarter-end anchor: {run.anchor_date.isoformat()}"]
    for ticker, quarter in sorted(run.company_quarters.items()):
        try:
            end = resolve_quarter_end_date(ticker, quarter)
            delta = abs((end - run.anchor_date).days)
            note = f" (reported period end {end.isoformat()}, delta {delta}d)"
        except FiscalCalendarError:
            note = ""
        lines.append(f"  {ticker}: {quarter}{note}")
    return "\n".join(lines)
