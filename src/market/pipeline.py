from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.ingest.dates import format_as_of_date
from src.ingest.filings.fiscal import normalize_quarter_label
from src.market.fiscal_calendar import (
    DEFAULT_FISCAL_CALENDARS_PATH,
    FiscalCalendarError,
    resolve_quarter_end_dates,
)
from src.market.models import QuarterEndPrice
from src.market.price_audit import save_price_audit
from src.market.prompt_block import format_price_block
from src.market.quarter_labels import (
    prior_quarter_labels,
    prior_quarter_labels_for_price_lookup,
)
from src.market.stock_prices import StockPriceError, fetch_quarter_end_prices
from src.pipeline.point_in_time import PointInTimeConfig


@dataclass(frozen=True)
class MarketContext:
    ticker: str
    as_of_date: date
    reported_quarter: str
    prior_labels: list[str]
    quarter_end_dates: dict[str, date]
    prices: list[QuarterEndPrice]
    price_block_text: str


def build_market_context(
    *,
    ticker: str,
    as_of_date: date,
    reported_quarter: str,
    audit_label: str,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    date_overrides: dict[str, date] | None = None,
    fetcher=None,
    point_in_time: PointInTimeConfig | None = None,
) -> MarketContext:
    pit = point_in_time or PointInTimeConfig.disabled()
    ticker_key = ticker.strip().upper()
    normalized_reported = normalize_quarter_label(reported_quarter)
    effective_overrides = dict(date_overrides or {})
    effective_overrides.setdefault(normalized_reported, as_of_date)
    prior_labels = prior_quarter_labels_for_price_lookup(
        normalized_reported,
        as_of_date,
        ticker_key,
        calendars_path=calendars_path,
        overrides=effective_overrides,
    )
    quarter_end_dates = resolve_quarter_end_dates(
        ticker_key,
        prior_labels,
        calendars_path=calendars_path,
        overrides=effective_overrides,
    )
    adjusted = not pit.unadjusted_prices
    prices = fetch_quarter_end_prices(
        ticker_key,
        quarter_end_dates,
        ordered_labels=prior_labels,
        fetcher=fetcher,
        as_of_date=as_of_date,
        adjusted=adjusted,
        strict=pit.active,
    )
    for price in prices:
        cap = price.cap_applied or min(price.quarter_end_date, as_of_date)
        if cap < price.quarter_end_date:
            import logging

            logging.getLogger(__name__).info(
                "Price lookup for %s capped at %s (quarter end %s, as_of %s)",
                price.quarter_label,
                cap.isoformat(),
                price.quarter_end_date.isoformat(),
                as_of_date.isoformat(),
            )
    price_block_text = format_price_block(
        ticker_key,
        prices,
        call_date=as_of_date,
        reported_quarter=normalized_reported,
        prior_labels=prior_labels,
        transcript_validated=pit.active,
    )
    audit_mode = (
        "point-in-time-with-prices"
        if pit.include_prices
        else "default"
    )
    save_price_audit(
        audit_label,
        ticker_key,
        prices,
        call_date=as_of_date,
        reported_quarter=normalized_reported,
        prior_labels=prior_labels,
        mode=audit_mode,
        strict=pit.active,
        adjusted=adjusted,
    )
    return MarketContext(
        ticker=ticker_key,
        as_of_date=as_of_date,
        reported_quarter=normalized_reported,
        prior_labels=prior_labels,
        quarter_end_dates=quarter_end_dates,
        prices=prices,
        price_block_text=price_block_text,
    )


def format_market_dry_run_lines(
    *,
    ticker: str,
    as_of_date: date,
    reported_quarter: str,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    date_overrides: dict[str, date] | None = None,
) -> list[str]:
    ticker_key = ticker.strip().upper()
    try:
        normalized_reported = normalize_quarter_label(reported_quarter)
        prior_labels = prior_quarter_labels_for_price_lookup(
            normalized_reported,
            as_of_date,
            ticker_key,
            calendars_path=calendars_path,
            overrides={**(date_overrides or {}), normalized_reported: as_of_date},
        )
        quarter_end_dates = resolve_quarter_end_dates(
            ticker_key,
            prior_labels,
            calendars_path=calendars_path,
            overrides={**(date_overrides or {}), normalized_reported: as_of_date},
        )
    except (FiscalCalendarError, StockPriceError) as exc:
        return [f"Market data: FAILED - {exc}"]

    lines = [
        f"Ticker: {ticker_key}",
        f"As-of date: {format_as_of_date(as_of_date)}",
        f"Reported quarter: {normalized_reported}",
        "Prior quarter end dates:",
    ]
    for label in prior_labels:
        normalized = normalize_quarter_label(label)
        end_date = quarter_end_dates[normalized]
        capped = min(end_date, as_of_date)
        lines.append(
            f"  - {normalized}: {end_date.isoformat()} "
            f"(price lookup cap: {capped.isoformat()})"
        )
    lines.append("Market data: OK (prices not fetched in dry run)")
    return lines


def format_point_in_time_dry_run_lines(
    *,
    as_of_date: date,
    reported_quarter: str,
    point_in_time: PointInTimeConfig,
    ticker: str | None = None,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    date_overrides: dict[str, date] | None = None,
) -> list[str]:
    mode_label = (
        "point-in-time-with-prices"
        if point_in_time.include_prices
        else "point-in-time (documents-only)"
    )
    lines = [
        f"Point-in-time mode: {mode_label}",
        "Rescue judge: disabled",
        f"Prices enabled: {'yes' if point_in_time.include_prices else 'no'}",
        f"As-of date: {format_as_of_date(as_of_date)}",
        f"Reported quarter: {normalize_quarter_label(reported_quarter)}",
        "Point-in-time validation: OK",
    ]
    if point_in_time.include_prices:
        lines.insert(
            4,
            f"Price type: {'close' if point_in_time.unadjusted_prices else 'adjusted close'}",
        )
    if ticker and point_in_time.include_prices:
        lines.extend(
            format_market_dry_run_lines(
                ticker=ticker,
                as_of_date=as_of_date,
                reported_quarter=reported_quarter,
                calendars_path=calendars_path,
                date_overrides=date_overrides,
            )
        )
    return lines
