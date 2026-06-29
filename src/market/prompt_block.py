from __future__ import annotations

from datetime import date

from src.ingest.call_date import format_call_date
from src.market.models import QuarterEndPrice

PRICE_BLOCK_HEADER = (
    "--- PRIOR QUARTER STOCK PRICES "
    "(source: yfinance adjusted close; not from transcript) ---"
)


def format_price_block(
    ticker: str,
    prices: list[QuarterEndPrice],
    *,
    call_date: date,
    reported_quarter: str,
    prior_labels: list[str],
) -> str:
    lines = [
        PRICE_BLOCK_HEADER,
        f"Ticker: {ticker.strip().upper()}",
        f"Call date: {format_call_date(call_date)}",
        f"Reported quarter (from transcript): {reported_quarter}",
        f"Prior {len(prior_labels)} quarter-ends (10 years): {', '.join(prior_labels)}",
    ]
    lines.extend(price.format_line() for price in prices)
    return "\n".join(lines)
