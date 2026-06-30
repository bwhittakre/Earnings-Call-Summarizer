from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.ingest.call_date import format_call_date, resolve_call_date_value
from src.ingest.loader import normalize_quarter_label, transcript_audit_label, TranscriptFile
from src.ingest.reported_quarter import ReportedQuarterError, extract_reported_quarter
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
from src.pipeline.point_in_time import PointInTimeConfig
from src.pipeline.strict_anchoring import resolve_strict_anchoring


@dataclass(frozen=True)
class MarketContext:
    ticker: str
    call_date: date
    reported_quarter: str
    prior_labels: list[str]
    quarter_end_dates: dict[str, date]
    prices: list[QuarterEndPrice]
    price_block_text: str


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
    point_in_time: PointInTimeConfig | None = None,
) -> MarketContext:
    pit = point_in_time or PointInTimeConfig.disabled()
    ticker_key = ticker.strip().upper()
    normalized_reported = normalize_quarter_label(reported_quarter)
    prior_labels = prior_quarter_labels(normalized_reported)
    quarter_end_dates = resolve_quarter_end_dates(
        ticker_key,
        prior_labels,
        calendars_path=calendars_path,
        overrides=date_overrides,
    )
    adjusted = not pit.unadjusted_prices
    prices = fetch_quarter_end_prices(
        ticker_key,
        quarter_end_dates,
        ordered_labels=prior_labels,
        fetcher=fetcher,
        as_of_date=call_date,
        adjusted=adjusted,
        strict=pit.active,
    )
    for price in prices:
        cap = price.cap_applied or min(price.quarter_end_date, call_date)
        if cap < price.quarter_end_date:
            import logging

            logging.getLogger(__name__).info(
                "Price lookup for %s capped at %s (quarter end %s, call %s)",
                price.quarter_label,
                cap.isoformat(),
                price.quarter_end_date.isoformat(),
                call_date.isoformat(),
            )
    price_block_text = format_price_block(
        ticker_key,
        prices,
        call_date=call_date,
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
        transcript_audit_label(transcript_file),
        ticker_key,
        prices,
        call_date=call_date,
        reported_quarter=normalized_reported,
        prior_labels=prior_labels,
        mode=audit_mode,
        strict=pit.active,
        adjusted=adjusted,
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
    filename_quarter: str | None = None,
    reported_quarter: str | None = None,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    date_overrides: dict[str, date] | None = None,
    point_in_time: PointInTimeConfig | None = None,
) -> list[str]:
    pit = point_in_time or PointInTimeConfig.disabled()
    ticker_key = ticker.strip().upper()
    try:
        if pit.active and filename_quarter:
            call_date, resolved_reported = resolve_strict_anchoring(
                transcript_text=transcript_text,
                filename_quarter=filename_quarter,
                point_in_time=pit,
                reported_quarter_override=reported_quarter,
            )
        else:
            call_date = resolve_call_date_value(transcript_text)
            from src.ingest.reported_quarter import resolve_reported_quarter

            resolved_reported = resolve_reported_quarter(
                transcript_text,
                cli_override=reported_quarter,
            )
        prior_labels = prior_quarter_labels(resolved_reported)
        quarter_end_dates = resolve_quarter_end_dates(
            ticker_key,
            prior_labels,
            calendars_path=calendars_path,
            overrides=date_overrides,
        )
    except (ReportedQuarterError, FiscalCalendarError, StockPriceError) as exc:
        return [f"Market data: FAILED - {exc}"]
    except Exception as exc:
        from src.pipeline.point_in_time import PointInTimeError

        if isinstance(exc, PointInTimeError):
            return [f"Point-in-time validation: FAILED - {exc}"]
        raise

    lines = [
        f"Ticker: {ticker_key}",
        f"Call date: {format_call_date(call_date)}",
        f"Reported quarter (transcript): {resolved_reported}",
    ]
    if filename_quarter:
        normalized_filename = normalize_quarter_label(filename_quarter)
        transcript_quarter = extract_reported_quarter(transcript_text)
        if transcript_quarter:
            match = (
                normalize_quarter_label(transcript_quarter)
                == normalized_filename
            )
            lines.append(
                f"Filename quarter: {normalized_filename} "
                f"(transcript match: {'OK' if match else 'MISMATCH'})"
            )
    lines.append("Prior quarter end dates:")
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


def format_point_in_time_dry_run_lines(
    *,
    transcript_text: str,
    filename_quarter: str,
    point_in_time: PointInTimeConfig,
    ticker: str | None = None,
    reported_quarter_override: str | None = None,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    date_overrides: dict[str, date] | None = None,
) -> list[str]:
    mode_label = (
        "point-in-time-with-prices"
        if point_in_time.include_prices
        else "point-in-time (transcript-only)"
    )
    lines = [
        f"Point-in-time mode: {mode_label}",
        f"Rescue judge: disabled",
        f"Prices enabled: {'yes' if point_in_time.include_prices else 'no'}",
    ]
    if point_in_time.include_prices:
        lines.append(
            f"Price type: {'close' if point_in_time.unadjusted_prices else 'adjusted close'}"
        )
    if ticker and point_in_time.include_prices:
        lines.extend(
            format_market_dry_run_lines(
                ticker=ticker,
                transcript_text=transcript_text,
                filename_quarter=filename_quarter,
                reported_quarter=reported_quarter_override,
                calendars_path=calendars_path,
                date_overrides=date_overrides,
                point_in_time=point_in_time,
            )
        )
    else:
        try:
            call_date, resolved_reported = resolve_strict_anchoring(
                transcript_text=transcript_text,
                filename_quarter=filename_quarter,
                point_in_time=point_in_time,
                reported_quarter_override=reported_quarter_override,
            )
        except Exception as exc:
            lines.append(f"Point-in-time validation: FAILED - {exc}")
            return lines
        lines.extend(
            [
                f"Call date: {format_call_date(call_date)}",
                f"Reported quarter (transcript): {resolved_reported}",
                f"Filename quarter: {normalize_quarter_label(filename_quarter)} (transcript match: OK)",
                "Point-in-time validation: OK",
            ]
        )
    return lines
