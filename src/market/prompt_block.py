from __future__ import annotations

from datetime import date

from src.ingest.dates import format_as_of_date
from src.market.models import QuarterEndPrice

ADJUSTED_PRICE_BLOCK_HEADER = (
    "--- PRIOR QUARTER STOCK PRICES "
    "(source: yfinance adjusted close; not from filings) ---"
)
UNADJUSTED_PRICE_BLOCK_HEADER = (
    "--- PRIOR QUARTER STOCK PRICES "
    "(source: yfinance close; not from filings) ---"
)


def format_price_block(
    ticker: str,
    prices: list[QuarterEndPrice],
    *,
    call_date: date,
    reported_quarter: str,
    prior_labels: list[str],
    transcript_validated: bool = False,
) -> str:
    adjusted = prices[0].adjusted if prices else True
    header = (
        ADJUSTED_PRICE_BLOCK_HEADER
        if adjusted
        else UNADJUSTED_PRICE_BLOCK_HEADER
    )
    reported_source = (
        "Reported quarter (filing-validated)"
        if transcript_validated
        else "Reported quarter (from filing package)"
    )
    lines = [
        header,
        f"Ticker: {ticker.strip().upper()}",
        f"As-of date: {format_as_of_date(call_date)}",
        f"{reported_source}: {reported_quarter}",
        f"Prior quarters priced: {', '.join(prior_labels)}",
    ]
    lines.extend(price.format_line() for price in prices)
    return "\n".join(lines)
