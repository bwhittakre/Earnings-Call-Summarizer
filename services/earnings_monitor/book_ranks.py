"""Worker/host runner for Structured Narrative book ranks (investable-as-of)."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .config import MonitorConfig
from .ticker_book import resolve_book_tickers

LOG = logging.getLogger(__name__)


def build_book_ranks_command(
    config: MonitorConfig,
    *,
    python: str | None = None,
    tickers: Sequence[str] | None = None,
    trigger_ticker: str | None = None,
    trigger_period: str | None = None,
    mode: str = "investable_asof",
    force_asof: bool = False,
) -> list[str]:
    script = config.repo_root / "Structured Narrative" / "build_book_ranks.py"
    book = list(tickers) if tickers is not None else list(resolve_book_tickers(config))
    if not book:
        book = list(config.tickers)
    cmd = [
        python or sys.executable,
        str(script),
        "--tickers",
        *book,
        "--mode",
        mode,
    ]
    if force_asof:
        cmd.append("--force-asof")
    if trigger_ticker:
        cmd.extend(["--trigger-ticker", trigger_ticker.strip().upper()])
    if trigger_period:
        cmd.extend(["--trigger-period", trigger_period.strip().upper()])
    return cmd


def run_book_ranks_subprocess(
    config: MonitorConfig,
    *,
    python: str | None = None,
    tickers: Sequence[str] | None = None,
    trigger_ticker: str | None = None,
    trigger_period: str | None = None,
    mode: str = "investable_asof",
    force_asof: bool = False,
) -> dict[str, Any]:
    """Run build_book_ranks.py; return a small status dict (never raises)."""
    sn_dir = config.repo_root / "Structured Narrative"
    if not sn_dir.is_dir():
        return {"ok": False, "error": f"missing Structured Narrative dir: {sn_dir}"}
    command = build_book_ranks_command(
        config,
        python=python,
        tickers=tickers,
        trigger_ticker=trigger_ticker,
        trigger_period=trigger_period,
        mode=mode,
        force_asof=force_asof,
    )
    LOG.info("Running book_ranks: %s", " ".join(command))
    try:
        completed = subprocess.run(
            command,
            cwd=str(sn_dir),
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        LOG.exception("book_ranks subprocess failed to start")
        return {"ok": False, "error": str(exc)}
    if completed.returncode != 0:
        LOG.error(
            "book_ranks failed code=%s stderr=%s",
            completed.returncode,
            (completed.stderr or "")[-500:],
        )
        return {
            "ok": False,
            "returncode": int(completed.returncode),
            "stderr": (completed.stderr or "")[-1000:],
        }
    return {
        "ok": True,
        "returncode": 0,
        "stdout_tail": (completed.stdout or "")[-1000:],
        "trigger_ticker": (trigger_ticker or "").upper() or None,
        "trigger_period": (trigger_period or "").upper() or None,
        "mode": mode,
    }


def _summary_path(config: MonitorConfig) -> Path:
    history = config.history_source_path
    if history is not None:
        root = Path(history)
        if root.name == "cross_company":
            return root / "json" / "book_ranks_summary.json"
        if root.name == "output" or (root / "cross_company").is_dir():
            return root / "cross_company" / "json" / "book_ranks_summary.json"
    return (
        config.repo_root
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "book_ranks_summary.json"
    )


def pending_investable_ranks_due(
    config: MonitorConfig,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return summary dict when an awaiting investable-asof build is now due."""
    path = _summary_path(config)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("skipped_reason") != "awaiting_investable_asof":
        return None
    as_of_raw = payload.get("as_of_date")
    if not as_of_raw:
        return None
    try:
        as_of = datetime.strptime(str(as_of_raw)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    if as_of > today:
        return None
    return payload


def maybe_run_pending_investable_ranks(
    config: MonitorConfig,
    *,
    python: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """If summary says awaiting and as-of ≤ today, rebuild ranks. Else None."""
    pending = pending_investable_ranks_due(config, now=now)
    if pending is None:
        return None
    LOG.info(
        "Investable-asof ranks due (bucket=%s as_of=%s); rebuilding",
        pending.get("period_bucket"),
        pending.get("as_of_date"),
    )
    return run_book_ranks_subprocess(
        config,
        python=python,
        trigger_ticker=pending.get("trigger_ticker"),
        trigger_period=pending.get("trigger_period"),
        mode="investable_asof",
        force_asof=False,
    )
