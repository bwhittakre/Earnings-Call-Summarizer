"""Discover/arm eligibility: Roz book ∩ onboarded company overlays."""

from __future__ import annotations

from pathlib import Path

from .config import MonitorConfig
from .state import OperationalState
from .ticker_book import resolve_book_tickers

OVERLAY_REL = Path("Structured Narrative") / "config" / "company_overlays"


def default_overlay_dir(repo_root: Path | str) -> Path:
    return Path(repo_root) / OVERLAY_REL


def list_overlay_tickers(overlay_dir: Path | str) -> frozenset[str]:
    """Return tickers that have ``{TICKER}.json`` overlays (already onboarded)."""
    root = Path(overlay_dir)
    if not root.is_dir():
        return frozenset()
    tickers: set[str] = set()
    for path in root.glob("*.json"):
        key = path.stem.strip().upper()
        if key:
            tickers.add(key)
    return frozenset(tickers)


def eligible_discovery_tickers(
    config: MonitorConfig,
    state: OperationalState | None = None,
    *,
    overlay_dir: Path | str | None = None,
) -> tuple[str, ...]:
    """Intersection of book/allowlist tickers and on-disk overlays.

    Uses ``resolve_book_tickers`` (SQLite meta, else env + sector file) so
    onboarded names stay discoverable after book sync without rewriting the
    monitor process env for every case.
    """
    overlays = list_overlay_tickers(
        Path(overlay_dir) if overlay_dir is not None else default_overlay_dir(config.repo_root)
    )
    if not overlays:
        return ()
    book = resolve_book_tickers(config, state)
    return tuple(ticker for ticker in book if ticker in overlays)


def ticker_is_eligible(
    ticker: str,
    config: MonitorConfig,
    state: OperationalState | None = None,
    *,
    overlay_dir: Path | str | None = None,
) -> bool:
    key = ticker.strip().upper()
    return key in eligible_discovery_tickers(
        config, state, overlay_dir=overlay_dir
    )
