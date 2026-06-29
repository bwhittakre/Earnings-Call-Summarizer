from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.ingest.call_date import format_call_date, parse_call_date_format, resolve_call_date
from src.ingest.loader import normalize_quarter_label, transcript_audit_label, TranscriptFile
from src.ingest.reported_quarter import ReportedQuarterError, resolve_reported_quarter
from src.market.constants import PRIOR_QUARTER_PRICE_COUNT
from src.market.fiscal_calendar import (
    DEFAULT_FISCAL_CALENDARS_PATH,
    FiscalCalendarError,
    resolve_quarter_end_dates,
)
from src.market.models import QuarterEndPrice
from src.market.price_audit import save_price_audit
from src.market.prompt_block import format_price_block
from src.market.quarter_labels import prior_quarter_labels
from src.market.stock_prices import StockPriceError, fetch_quarter_end_prices


@dataclass(frozen=True)
class MarketContext:
    ticker: str
    call_date: date
    reported_quarter: str
    prior_labels: list[str]
    quarter_end_dates: dict[str, date]
    prices: list[QuarterEndPrice]
    price_block_text: str


def resolve_call_date_value(transcript_text: str) -> date:
    call_date_text = resolve_call_date(transcript_text)
    if not call_date_text:
        raise ReportedQuarterError(
            "Could not extract call date from transcript. "
            "Market data requires a call date in IR opening remarks."
        )
    parsed = parse_call_date_format(call_date_text)
    if parsed is None:
        raise ReportedQuarterError(f"Invalid call date format: {call_date_text!r}")
    return parsed


def build_market_context(
    *,
    ticker: str,
    transcript_text: str,
    call_date: date,
    reported_quarter: str,
    transcript_file: TranscriptFile,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    date_overrides: dict[str, date] | None = None,
    fetcher=None,
    price_history_quarters: int = PRIOR_QUARTER_PRICE_COUNT,
) -> MarketContext:
    ticker_key = ticker.strip().upper()
    normalized_reported = normalize_quarter_label(reported_quarter)
    prior_labels = prior_quarter_labels(
        normalized_reported,
        count=price_history_quarters,
    )
    quarter_end_dates = resolve_quarter_end_dates(
        ticker_key,
        prior_labels,
        calendars_path=calendars_path,
        overrides=date_overrides,
    )
    prices = fetch_quarter_end_prices(
        ticker_key,
        quarter_end_dates,
        ordered_labels=prior_labels,
        fetcher=fetcher,
        as_of_date=call_date,
    )
    price_block_text = format_price_block(
        ticker_key,
        prices,
        call_date=call_date,
        reported_quarter=normalized_reported,
        prior_labels=prior_labels,
    )
    save_price_audit(
        transcript_audit_label(transcript_file),
        ticker_key,
        prices,
        call_date=call_date,
        reported_quarter=normalized_reported,
        prior_labels=prior_labels,
    )
    return MarketContext(
        ticker=ticker_key,
        call_date=call_date,
        reported_quarter=normalized_reported,
        prior_labels=prior_labels,
        quarter_end_dates=quarter_end_dates,
        prices=prices,
        price_block_text=price_block_text,
    )


def format_market_dry_run_lines(
    *,
    ticker: str,
    transcript_text: str,
    reported_quarter: str | None = None,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    date_overrides: dict[str, date] | None = None,
    price_history_quarters: int = PRIOR_QUARTER_PRICE_COUNT,
) -> list[str]:
    ticker_key = ticker.strip().upper()
    try:
        call_date = resolve_call_date_value(transcript_text)
        resolved_reported = resolve_reported_quarter(
            transcript_text,
            cli_override=reported_quarter,
        )
        prior_labels = prior_quarter_labels(
            resolved_reported,
            count=price_history_quarters,
        )
        quarter_end_dates = resolve_quarter_end_dates(
            ticker_key,
            prior_labels,
            calendars_path=calendars_path,
            overrides=date_overrides,
        )
    except (ReportedQuarterError, FiscalCalendarError) as exc:
        return [f"Market data: FAILED - {exc}"]

    lines = [
        f"Ticker: {ticker_key}",
        f"Call date: {format_call_date(call_date)}",
        f"Reported quarter (transcript): {resolved_reported}",
        "Prior quarter end dates:",
    ]
    for label in prior_labels:
        normalized = normalize_quarter_label(label)
        end_date = quarter_end_dates[normalized]
        capped = min(end_date, call_date)
        lines.append(
            f"  - {normalized}: {end_date.isoformat()} "
            f"(price lookup cap: {capped.isoformat()})"
        )
    lines.append("Market data: OK (prices not fetched in dry run)")
    return lines
