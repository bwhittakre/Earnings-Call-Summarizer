from __future__ import annotations

import threading
from datetime import date

from src.market.stock_prices import HistoryFetcher, _default_history_fetcher

_history_cache: dict[tuple[str, date, date], list[tuple[date, float]]] = {}
_history_lock = threading.Lock()


def cached_history_fetcher(
    ticker: str,
    start: date,
    end: date,
) -> list[tuple[date, float]]:
    ticker_key = ticker.strip().upper()
    key = (ticker_key, start, end)
    with _history_lock:
        cached = _history_cache.get(key)
    if cached is not None:
        return cached
    rows = _default_history_fetcher(ticker_key, start, end)
    with _history_lock:
        _history_cache[key] = rows
    return rows


def clear_history_cache() -> None:
    with _history_lock:
        _history_cache.clear()


def batch_history_fetcher() -> HistoryFetcher:
    return cached_history_fetcher
