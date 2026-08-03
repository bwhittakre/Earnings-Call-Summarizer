"""Sector / grouping helpers for Roz comparative views."""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from src.ingest.company_lists import (
    DEFAULT_SECTORS_DIR,
    list_available_sectors,
    load_sector_companies,
)

ALL_COMPANIES = "All Companies"


def list_sector_options(*, sectors_dir: Path | None = None) -> list[str]:
    """Return ``All Companies`` plus sector stems from ``config/sectors/``."""
    directory = sectors_dir or DEFAULT_SECTORS_DIR
    return [ALL_COMPANIES, *list_available_sectors(sectors_dir=directory)]


def resolve_sector_tickers(
    choice: str,
    available_tickers: Sequence[str],
    *,
    sectors_dir: Path | None = None,
) -> list[str]:
    """Resolve a sector choice to tickers present in *available_tickers*.

    ``All Companies`` returns the available list (sorted as provided).
    Named sectors keep the sector-file order, intersecting with available.
    """
    available = [str(ticker).upper() for ticker in available_tickers]
    available_set = set(available)
    if not choice or choice == ALL_COMPANIES:
        return available

    directory = sectors_dir or DEFAULT_SECTORS_DIR
    try:
        sector_tickers = [
            str(ticker).upper()
            for ticker in load_sector_companies(choice, sectors_dir=directory)
        ]
    except Exception:  # noqa: BLE001 — unknown sector falls back to all
        return available

    return [ticker for ticker in sector_tickers if ticker in available_set]


def pad_company_rows(
    rows: Sequence[dict],
    universe: Sequence[str],
    *,
    ticker_key: str = "ticker",
) -> list[dict]:
    """Left-join *rows* onto *universe* so every ticker appears once."""
    by_ticker: dict[str, dict] = {}
    for row in rows:
        ticker = str(row.get(ticker_key, "")).upper()
        if ticker:
            by_ticker[ticker] = dict(row)
            by_ticker[ticker][ticker_key] = ticker

    padded: list[dict] = []
    for ticker in universe:
        key = str(ticker).upper()
        if key in by_ticker:
            padded.append(by_ticker[key])
        else:
            padded.append({ticker_key: key})
    return padded
