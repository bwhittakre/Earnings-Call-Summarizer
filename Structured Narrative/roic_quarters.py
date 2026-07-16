#!/usr/bin/env python3
"""Resolve the N most recent ROIC.ai earnings-call quarters per ticker."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
RAW = HERE / "transcripts_raw"
DEFAULT_LAST_N = 8
_PERIOD = re.compile(r"^FY(\d{4})-Q([1-4])$", re.IGNORECASE)


def earnings_scraper_root() -> Path | None:
    desktop = REPO.parent
    for candidate in (
        desktop / "earnings-scraper-main" / "earnings-scraper-main",
        desktop / "earnings-scraper-main",
    ):
        if (candidate / "scripts" / "fetch_transcripts.py").is_file():
            return candidate
    return None


def load_roic_api_key() -> str:
    key = os.environ.get("ROIC_API_KEY", "").strip()
    if key:
        return key
    root = earnings_scraper_root()
    if root is None:
        return ""
    for name in ("roic_api", "roic_api.txt"):
        path = root / "secrets" / name
        try:
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
        except OSError:
            continue
    return ""


def fiscal_period_sort_key(fiscal_period: str) -> tuple[int, int]:
    m = _PERIOD.match(fiscal_period.strip().upper())
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)))


def _period_from_path(path: Path, ticker: str) -> str | None:
    stem = path.stem
    if stem.startswith(f"{ticker}_"):
        fp = stem[len(ticker) + 1 :]
    elif stem.upper().startswith("FY"):
        fp = stem.upper()
    else:
        return None
    m = _PERIOD.match(fp)
    return f"FY{m.group(1)}-Q{m.group(2)}" if m else None


def local_transcript_quarters(ticker: str) -> list[str]:
    """All fiscal periods with a local transcript file for *ticker*."""
    t = ticker.upper()
    found: set[str] = set()
    for path in RAW.glob(f"{t}_*.txt"):
        fp = _period_from_path(path, t)
        if fp:
            found.add(fp)
    ticker_dir = HERE / t
    if ticker_dir.is_dir():
        for path in ticker_dir.glob("*.txt"):
            fp = _period_from_path(path, t)
            if fp:
                found.add(fp)
    return sorted(found, key=fiscal_period_sort_key)


def last_n_quarters(ticker: str, n: int = DEFAULT_LAST_N) -> list[str]:
    """The *n* most recent local transcript quarters for *ticker*."""
    qs = local_transcript_quarters(ticker)
    return qs[-n:] if len(qs) > n else qs


def list_roic_calls(ticker: str, n: int = DEFAULT_LAST_N) -> list[str]:
    """Query ROIC.ai list endpoint; return FY labels newest-first, truncated to *n*."""
    key = load_roic_api_key()
    if not key:
        return []
    root = earnings_scraper_root()
    if root is None:
        return []
    env = os.environ.copy()
    env["ROIC_API_KEY"] = key
    env["PYTHONPATH"] = str(root / "src")
    t = ticker.upper()
    script = (
        "from earnings_scraper import roic_client\n"
        f"calls = roic_client.list_calls({t!r}, limit={n})\n"
        f"for c in calls[:{n}]:\n"
        "    print(f\"FY{c['year']}-Q{c['quarter']}\")\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def fetch_roic_transcripts(
    tickers: list[str],
    *,
    last_n: int = DEFAULT_LAST_N,
    force: bool = False,
) -> int:
    """Fetch the last *last_n* ROIC.ai transcripts into the earnings-scraper inbox."""
    root = earnings_scraper_root()
    if root is None:
        print("Warning: earnings-scraper not found; skipping ROIC fetch.", file=sys.stderr)
        return 0
    key = load_roic_api_key()
    if not key:
        print(
            "Warning: ROIC_API_KEY unset (set env or earnings-scraper/secrets/roic_api).",
            file=sys.stderr,
        )
        return 0
    env = os.environ.copy()
    env["ROIC_API_KEY"] = key
    env["PYTHONPATH"] = str(root / "src")
    cmd = [
        sys.executable,
        str(root / "scripts" / "fetch_transcripts.py"),
        *[t.upper() for t in tickers],
        "--last",
        str(last_n),
    ]
    if force:
        cmd.append("--force")
    result = subprocess.run(cmd, cwd=root, env=env)
    return result.returncode


def bridge_inbox(tickers: list[str]) -> None:
    from export_inbox_to_transcripts_raw import bridge_inbox as _bridge

    _bridge(tickers=[t.upper() for t in tickers])


def resolve_scoring_quarters(
    ticker: str,
    *,
    last_n: int = DEFAULT_LAST_N,
    prefer_roic_list: bool = True,
) -> list[str]:
    """
    Quarters to score: intersection of ROIC last-N (when available) and local files.
    Falls back to the last *n* local transcript files.
    """
    t = ticker.upper()
    roic = list_roic_calls(t, n=last_n) if prefer_roic_list else []
    local = set(local_transcript_quarters(t))
    if roic:
        qs = [q for q in roic if q in local]
        if qs:
            return sorted(qs, key=fiscal_period_sort_key)
        # ROIC listed quarters not yet bridged — use ROIC labels for fetch target display
        return sorted(roic, key=fiscal_period_sort_key)
    return last_n_quarters(t, last_n)


def write_quarter_manifest(
    tickers: list[str],
    *,
    last_n: int = DEFAULT_LAST_N,
    path: Path | None = None,
) -> dict[str, list[str]]:
    out_path = path or (HERE / "output" / "cross_company" / "json" / "roic_last_8_quarters.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    by_ticker = {t.upper(): resolve_scoring_quarters(t, last_n=last_n) for t in tickers}
    union = sorted({q for qs in by_ticker.values() for q in qs}, key=fiscal_period_sort_key)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": "ROIC.ai --last N (most recent available earnings calls)",
        "last_n": last_n,
        "by_ticker": by_ticker,
        "union_quarters": union,
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return by_ticker
