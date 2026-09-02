"""Discover/arm eligibility: which companies the monitor watches.

Who we watch for earnings calls and who Rank IC ranks against each other are
different questions. They were a single list while both happened to be the same
tech names, so discovery intersected the research book with the overlays. The
healthcare onboard was the first time the two diverged -- it deliberately kept
20 names out of the research book, and that silently removed them from
discovery as well.

An overlay is written by onboard, so its presence is the durable record that a
company joined Roz. Overlays therefore define the monitored universe, while
``roz_book_tickers`` stays the research comparison set.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from .config import MonitorConfig
from .state import OperationalState
from .ticker_book import resolve_book_tickers

LOG = logging.getLogger(__name__)

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


def registry_tickers(repo_root: Path | str) -> frozenset[str]:
    """Companies onboarded before overlays existed, still only in ``COMPANIES``.

    The original tech book predates the overlay format, so those names have no
    overlay file at all. ``get_company`` treats the in-code registry and on-disk
    overlays as equally valid onboarding records, and discovery has to agree --
    keying only on overlays would leave AAPL, MSFT and the rest unwatched.

    The module-identity check matters: ``company_config`` is imported by ticker
    name into a process-wide cache, so without it a test using a temp repo_root
    would silently inherit the real repo's registry.
    """
    sn = (Path(repo_root) / "Structured Narrative").resolve()
    if not (sn / "company_config.py").is_file():
        return frozenset()
    if str(sn) not in sys.path:
        sys.path.insert(0, str(sn))
    try:
        import company_config  # type: ignore
    except Exception:  # pragma: no cover - registry is best-effort
        LOG.warning("company_config unavailable at %s; using overlays only", sn)
        return frozenset()
    loaded = Path(getattr(company_config, "__file__", "") or "").resolve().parent
    if loaded != sn:
        return frozenset()
    return frozenset(
        str(ticker).strip().upper()
        for ticker in company_config.COMPANIES
        if str(ticker).strip()
    )


def monitored_universe_tickers(
    config: MonitorConfig,
    *,
    overlay_dir: Path | str | None = None,
) -> tuple[str, ...]:
    """Every onboarded company, minus explicit opt-outs.

    Excluding a name is deliberate and reversible via
    ``EARNINGS_MONITOR_EXCLUDE_TICKERS``, so a company can be taken off watch
    without deleting the record that it was onboarded.
    """
    overlays = list_overlay_tickers(
        Path(overlay_dir) if overlay_dir is not None else default_overlay_dir(config.repo_root)
    )
    onboarded = overlays | registry_tickers(config.repo_root)
    return tuple(sorted(onboarded - frozenset(config.monitor_excluded_tickers)))


def eligible_discovery_tickers(
    config: MonitorConfig,
    state: OperationalState | None = None,
    *,
    overlay_dir: Path | str | None = None,
) -> tuple[str, ...]:
    """Tickers discovery may arm.

    ``overlays`` (the default) watches everything onboarded. ``book`` is the
    legacy intersection with the research book, kept as a one-env-var rollback
    if widening discovery turns out to be disruptive.
    """
    if config.monitor_universe_mode != "book":
        return monitored_universe_tickers(config, overlay_dir=overlay_dir)
    overlays = list_overlay_tickers(
        Path(overlay_dir) if overlay_dir is not None else default_overlay_dir(config.repo_root)
    )
    if not overlays:
        return ()
    excluded = frozenset(config.monitor_excluded_tickers)
    book = resolve_book_tickers(config, state)
    return tuple(
        ticker for ticker in book if ticker in overlays and ticker not in excluded
    )


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
