"""Roz comparative book allowlist (monitor + research-regen + sector file).

First-Print and Onboard must integrate new tickers into the shared book so
Rank IC (``--tickers``) and consolidated HTML (``--sector``) stay aligned.
Runtime source of truth for live containers is SQLite ``roz_book_tickers``;
the sector file and env file are kept in sync when writable.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .config import MonitorConfig
from .state import OperationalState

LOG = logging.getLogger(__name__)

BOOK_META_KEY = "roz_book_tickers"
_TICKER_LINE_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")
_ENV_TICKERS_RE = re.compile(
    r"^(\s*EARNINGS_MONITOR_TICKERS\s*=\s*)(.*)$",
    re.MULTILINE,
)


@dataclass(frozen=True)
class BookIntegrationResult:
    ticker: str
    tickers: tuple[str, ...]
    added: bool
    sector_path: str | None
    sector_updated: bool
    env_path: str | None
    env_updated: bool
    meta_updated: bool


def sector_tickers_path(repo_root: Path, sector: str) -> Path:
    return Path(repo_root) / "config" / "sectors" / f"{sector}.txt"


def load_sector_tickers(path: Path) -> list[str]:
    if not path.is_file():
        return []
    tickers: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        key = line.upper()
        if _TICKER_LINE_RE.fullmatch(key) and key not in tickers:
            tickers.append(key)
    return tickers


def write_sector_ticker(path: Path, ticker: str) -> bool:
    """Append ticker to sector file. Returns True when the file changed."""
    ticker_key = ticker.strip().upper()
    if not _TICKER_LINE_RE.fullmatch(ticker_key):
        raise ValueError(f"Invalid ticker for sector book: {ticker!r}")
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_sector_tickers(path)
    if ticker_key in existing:
        return False
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        suffix = "" if text.endswith("\n") or not text else "\n"
        path.write_text(f"{text}{suffix}{ticker_key}\n", encoding="utf-8")
    else:
        path.write_text(
            f"# Roz comparative universe\n{ticker_key}\n",
            encoding="utf-8",
        )
    return True


def upsert_env_tickers(path: Path, ticker: str) -> bool:
    """Add ticker to EARNINGS_MONITOR_TICKERS in an env file when present."""
    ticker_key = ticker.strip().upper()
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8")
    match = _ENV_TICKERS_RE.search(text)
    if not match:
        addition = f"EARNINGS_MONITOR_TICKERS={ticker_key}\n"
        suffix = "" if text.endswith("\n") or not text else "\n"
        path.write_text(f"{text}{suffix}{addition}", encoding="utf-8")
        return True
    raw_list = match.group(2).strip().strip("\"'")
    current = [
        part.strip().upper()
        for part in raw_list.split(",")
        if part.strip()
    ]
    if ticker_key in current:
        return False
    current.append(ticker_key)
    updated = ",".join(dict.fromkeys(current))
    new_text = (
        text[: match.start()]
        + f"{match.group(1)}{updated}"
        + text[match.end() :]
    )
    path.write_text(new_text, encoding="utf-8")
    return True


def _normalize_tickers(values: Sequence[str]) -> list[str]:
    out: list[str] = []
    for raw in values:
        key = str(raw).strip().upper()
        if _TICKER_LINE_RE.fullmatch(key) and key not in out:
            out.append(key)
    return out


def _meta_tickers(state: OperationalState | None) -> list[str] | None:
    if state is None:
        return None
    raw = state.get_meta(BOOK_META_KEY)
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if isinstance(payload, dict):
        values = payload.get("tickers") or []
    elif isinstance(payload, list):
        values = payload
    else:
        return None
    if not isinstance(values, list):
        return None
    return _normalize_tickers([str(item) for item in values])


def resolve_book_tickers(
    config: MonitorConfig,
    state: OperationalState | None = None,
) -> tuple[str, ...]:
    """Prefer SQLite book meta; else union env tickers + sector file."""
    meta = _meta_tickers(state)
    if meta:
        return tuple(meta)
    sector_path = sector_tickers_path(config.repo_root, config.research_sector)
    merged = _normalize_tickers(
        list(config.tickers) + load_sector_tickers(sector_path)
    )
    return tuple(merged)


def seed_book_if_empty(
    config: MonitorConfig,
    state: OperationalState,
) -> tuple[str, ...]:
    """Persist the resolved book when meta is missing (first regen loop start)."""
    existing = _meta_tickers(state)
    if existing:
        return tuple(existing)
    tickers = resolve_book_tickers(config, state=None)
    state.set_meta(
        BOOK_META_KEY,
        json.dumps({"tickers": list(tickers)}, sort_keys=True),
    )
    return tickers


def _candidate_env_files(config: MonitorConfig) -> list[Path]:
    candidates: list[Path] = []
    for key in (
        "EARNINGS_MONITOR_TICKER_ENV_FILE",
        "EARNINGS_MONITOR_ENV_FILE",
    ):
        raw = os.environ.get(key)
        if raw:
            candidates.append(Path(raw))
    root = Path(config.repo_root)
    candidates.extend(
        [
            root / "services" / "earnings_monitor" / ".env.sim.local",
            root / "services" / "earnings_monitor" / ".env.local",
            root / "services" / "earnings_monitor" / ".env",
        ]
    )
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[Path] = []
    for path in candidates:
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


def ensure_ticker_in_book(
    *,
    ticker: str,
    config: MonitorConfig,
    state: OperationalState | None = None,
    seed_tickers: Sequence[str] = (),
) -> BookIntegrationResult:
    """Ensure ticker is in the Roz book (meta + sector file + env when possible)."""
    ticker_key = ticker.strip().upper()
    if not _TICKER_LINE_RE.fullmatch(ticker_key):
        raise ValueError(f"Invalid ticker for Roz book: {ticker!r}")

    current = list(
        _meta_tickers(state)
        or _normalize_tickers(
            list(seed_tickers)
            or list(config.tickers)
            + load_sector_tickers(
                sector_tickers_path(config.repo_root, config.research_sector)
            )
        )
    )
    added = ticker_key not in current
    if added:
        current.append(ticker_key)
    tickers = tuple(_normalize_tickers(current))

    meta_updated = False
    if state is not None:
        state.set_meta(
            BOOK_META_KEY,
            json.dumps({"tickers": list(tickers)}, sort_keys=True),
        )
        meta_updated = True

    sector_path = sector_tickers_path(config.repo_root, config.research_sector)
    sector_updated = False
    try:
        sector_updated = write_sector_ticker(sector_path, ticker_key)
    except OSError as exc:
        LOG.warning("Could not update sector file %s: %s", sector_path, exc)

    env_updated = False
    env_path_used: str | None = None
    for env_path in _candidate_env_files(config):
        try:
            if not env_path.is_file():
                continue
            before = env_path.read_text(encoding="utf-8")
            changed = upsert_env_tickers(env_path, ticker_key)
            if changed:
                env_updated = True
                env_path_used = str(env_path)
                LOG.info("Added %s to %s", ticker_key, env_path)
                break
            match = _ENV_TICKERS_RE.search(before)
            if match and ticker_key in {
                part.strip().upper()
                for part in match.group(2).split(",")
                if part.strip()
            }:
                env_path_used = str(env_path)
                break
        except OSError as exc:
            LOG.warning("Could not update env file %s: %s", env_path, exc)

    if added:
        LOG.info(
            "Integrated %s into Roz book (%s tickers; sector_updated=%s meta=%s)",
            ticker_key,
            len(tickers),
            sector_updated,
            meta_updated,
        )
    result = BookIntegrationResult(
        ticker=ticker_key,
        tickers=tickers,
        added=added,
        sector_path=str(sector_path),
        sector_updated=sector_updated,
        env_path=env_path_used,
        env_updated=env_updated,
        meta_updated=meta_updated,
    )
    return result

