from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from src.ingest.loader import normalize_quarter_label
from src.market.models import QuarterEndPrice


class StockPriceError(Exception):
    pass


HistoryFetcher = Callable[[str, date, date], list[tuple[date, float]]]

LOOKBACK_DAYS = 14


def _default_history_fetcher(
    ticker: str,
    start: date,
    end: date,
) -> list[tuple[date, float]]:
    import yfinance as yf

    history = yf.Ticker(ticker).history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=True,
    )
    if history.empty:
        return []
    rows: list[tuple[date, float]] = []
    for index, row in history.iterrows():
        rows.append((index.date(), float(row["Close"])))
    return rows


def _last_trading_close_on_or_before_from_rows(
    rows: list[tuple[date, float]],
    target: date,
) -> tuple[date, float]:
    eligible = [(day, close) for day, close in rows if day <= target]
    if not eligible:
        raise StockPriceError(
            f"No trading data on or before {target.isoformat()}."
        )
    return eligible[-1]


def _last_trading_close_on_or_before(
    ticker: str,
    target: date,
    fetcher: HistoryFetcher,
    *,
    as_of_date: date | None = None,
) -> tuple[date, float]:
    cap = as_of_date or date.today()
    effective_target = min(target, cap)
    start = effective_target - timedelta(days=LOOKBACK_DAYS)
    rows = fetcher(ticker, start, effective_target)
    return _last_trading_close_on_or_before_from_rows(rows, effective_target)


def fetch_quarter_end_prices(
    ticker: str,
    quarter_dates: dict[str, date],
    *,
    ordered_labels: list[str] | None = None,
    fetcher: HistoryFetcher | None = None,
    as_of_date: date | None = None,
) -> list[QuarterEndPrice]:
    history_fetcher = fetcher or _default_history_fetcher
    ticker_key = ticker.strip().upper()
    labels = ordered_labels or list(quarter_dates.keys())
    if not labels:
        return []

    cap = as_of_date or date.today()
    effective_targets = [
        min(quarter_dates[normalize_quarter_label(label)], cap)
        for label in labels
    ]
    earliest_target = min(effective_targets)
    latest_target = max(effective_targets)
    history_start = earliest_target - timedelta(days=LOOKBACK_DAYS)
    history_rows = history_fetcher(ticker_key, history_start, latest_target)

    prices: list[QuarterEndPrice] = []
    for quarter_label in labels:
        normalized = normalize_quarter_label(quarter_label)
        if normalized not in quarter_dates:
            raise StockPriceError(
                f"Missing quarter-end date for {normalized!r}."
            )
        quarter_end_date = quarter_dates[normalized]
        effective_target = min(quarter_end_date, cap)
        price_date, adjusted_close = _last_trading_close_on_or_before_from_rows(
            history_rows,
            effective_target,
        )
        prices.append(
            QuarterEndPrice(
                quarter_label=normalized,
                quarter_end_date=quarter_end_date,
                price_date=price_date,
                adjusted_close=adjusted_close,
                ticker=ticker_key,
            )
        )
    return prices
