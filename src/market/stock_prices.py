from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from src.ingest.filings.fiscal import normalize_quarter_label
from src.market.models import QuarterEndPrice


class StockPriceError(Exception):
    pass


HistoryFetcher = Callable[[str, date, date], list[tuple[date, float]]]


def _default_history_fetcher(
    ticker: str,
    start: date,
    end: date,
    *,
    adjusted: bool = True,
) -> list[tuple[date, float]]:
    import yfinance as yf

    history = yf.Ticker(ticker).history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        auto_adjust=adjusted,
    )
    if history.empty:
        return []
    rows: list[tuple[date, float]] = []
    for index, row in history.iterrows():
        rows.append((index.date(), float(row["Close"])))
    return rows


def make_default_history_fetcher(*, adjusted: bool = True) -> HistoryFetcher:
    def fetcher(ticker: str, start: date, end: date) -> list[tuple[date, float]]:
        return _default_history_fetcher(ticker, start, end, adjusted=adjusted)

    return fetcher


def _last_trading_close_on_or_before(
    ticker: str,
    target: date,
    fetcher: HistoryFetcher,
    *,
    as_of_date: date | None = None,
) -> tuple[date, float, date]:
    cap = as_of_date or date.today()
    effective_target = min(target, cap)
    start = effective_target - timedelta(days=14)
    rows = fetcher(ticker, start, effective_target)
    eligible = [(day, close) for day, close in rows if day <= effective_target]
    if not eligible:
        raise StockPriceError(
            f"No trading data for {ticker} on or before {effective_target.isoformat()}."
        )
    day, close = eligible[-1]
    return day, close, effective_target


def validate_prices_point_in_time(
    prices: list[QuarterEndPrice],
    call_date: date,
) -> None:
    for price in prices:
        if price.price_date > call_date:
            raise StockPriceError(
                f"Price date {price.price_date.isoformat()} for "
                f"{price.quarter_label} exceeds call date {call_date.isoformat()}."
            )


def fetch_quarter_end_prices(
    ticker: str,
    quarter_dates: dict[str, date],
    *,
    ordered_labels: list[str] | None = None,
    fetcher: HistoryFetcher | None = None,
    as_of_date: date | None = None,
    adjusted: bool = True,
    strict: bool = False,
) -> list[QuarterEndPrice]:
    history_fetcher = fetcher or make_default_history_fetcher(adjusted=adjusted)
    ticker_key = ticker.strip().upper()
    labels = ordered_labels or list(quarter_dates.keys())
    prices: list[QuarterEndPrice] = []
    for quarter_label in labels:
        normalized = normalize_quarter_label(quarter_label)
        if normalized not in quarter_dates:
            raise StockPriceError(
                f"Missing quarter-end date for {normalized!r}."
            )
        quarter_end_date = quarter_dates[normalized]
        price_date, close, cap_applied = _last_trading_close_on_or_before(
            ticker_key,
            quarter_end_date,
            history_fetcher,
            as_of_date=as_of_date,
        )
        prices.append(
            QuarterEndPrice(
                quarter_label=normalized,
                quarter_end_date=quarter_end_date,
                price_date=price_date,
                adjusted_close=close,
                ticker=ticker_key,
                adjusted=adjusted,
                cap_applied=cap_applied,
            )
        )
    if strict and as_of_date is not None:
        validate_prices_point_in_time(prices, as_of_date)
    return prices
