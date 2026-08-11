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
CUSTOM_LIST = "Custom List"


def list_sector_options(*, sectors_dir: Path | None = None) -> list[str]:
    """Return ``All Companies``, ``Custom List``, then sector stems."""
    directory = sectors_dir or DEFAULT_SECTORS_DIR
    stems = list_available_sectors(sectors_dir=directory)
    # Pretty-print Quartr-synced lists while keeping file stems as values
    # is handled by list_sector_option_labels; options themselves stay stems.
    return [ALL_COMPANIES, CUSTOM_LIST, *stems]


def sector_option_label(choice: str) -> str:
    """Human label for a sector selectbox option."""
    if choice.startswith("quartr_"):
        pretty = choice.removeprefix("quartr_").replace("_", " ").strip()
        return f"Quartr: {pretty}" if pretty else "Quartr"
    return choice


def resolve_sector_tickers(
    choice: str,
    available_tickers: Sequence[str],
    *,
    sectors_dir: Path | None = None,
    custom_tickers: Sequence[str] | None = None,
) -> list[str]:
    """Resolve a sector choice to tickers present in *available_tickers*.

    ``All Companies`` returns the available list.
    ``Custom List`` returns *custom_tickers* intersected with available.
    Named sectors keep the sector-file order, intersecting with available.
    """
    available = [str(ticker).upper() for ticker in available_tickers]
    available_set = set(available)
    if not choice or choice == ALL_COMPANIES:
        return available

    if choice == CUSTOM_LIST:
        selected = [
            str(ticker).upper()
            for ticker in (custom_tickers or ())
            if str(ticker).strip()
        ]
        return [ticker for ticker in selected if ticker in available_set]

    directory = sectors_dir or DEFAULT_SECTORS_DIR
    try:
        sector_tickers = [
            str(ticker).upper()
            for ticker in load_sector_companies(choice, sectors_dir=directory)
        ]
    except Exception:  # noqa: BLE001 — unknown sector falls back to all
        return available

    return [ticker for ticker in sector_tickers if ticker in available_set]


def resolve_active_universe(
    choice: str,
    available_tickers: Sequence[str],
    *,
    custom_tickers: Sequence[str] | None = None,
    sectors_dir: Path | None = None,
) -> list[str]:
    """Alias for resolve_sector_tickers with Custom List support."""
    return resolve_sector_tickers(
        choice,
        available_tickers,
        sectors_dir=sectors_dir,
        custom_tickers=custom_tickers,
    )


def is_full_universe(
    sector_tickers: Sequence[str] | None,
    available_tickers: Sequence[str],
) -> bool:
    """True when the active filter is effectively the full available set."""
    if sector_tickers is None:
        return True
    available = {str(t).upper() for t in available_tickers if str(t).strip()}
    active = {str(t).upper() for t in sector_tickers if str(t).strip()}
    return bool(available) and active == available


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
