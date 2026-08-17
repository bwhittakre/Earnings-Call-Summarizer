"""Micro-onboard: pull and score only the most recent earnings call.

Used when Quartr watchlist sync discovers a company not yet in Roz. Deep
history remains a separate full Onboard.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

from .config import MonitorConfig
from .onboard import (
    OnboardError,
    _run_command,
    allowlist_guidance,
    discover_on_disk_periods,
    ensure_fiscal_calendar_entry,
    register_overlay_profile,
    write_company_overlay,
)
from .ticker_book import ensure_ticker_in_book

LOG = logging.getLogger(__name__)


@dataclass
class LatestOnboardResult:
    ticker: str
    status: str = "started"
    fiscal_period: str | None = None
    company_id: int | None = None
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    allowlist_guidance: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _panel_exists(repo_root: Path, ticker: str) -> bool:
    sn = repo_root / "Structured Narrative"
    panel = sn / "output" / ticker / "parquet" / "feature_panel.parquet"
    panel_csv = sn / "output" / ticker / "csv" / "feature_panel.csv"
    return panel.is_file() or panel_csv.is_file()


def run_latest_call_onboard(
    *,
    repo_root: Path,
    ticker: str,
    company_name: str | None = None,
    dry_run: bool = False,
    skip_llm: bool = False,
    skip_quant: bool = False,
    lookback_days: int = 400,
    configured_tickers: Sequence[str] = (),
    state=None,
    run_command: Callable[..., dict[str, Any]] | None = None,
    now: datetime | None = None,
) -> LatestOnboardResult:
    """Pull the newest Quartr transcript and score that single quarter."""
    ticker_key = ticker.strip().upper()
    name = company_name or ticker_key
    current = now or datetime.now(timezone.utc)
    runner = run_command or _run_command
    sn = Path(repo_root) / "Structured Narrative"
    py = sys.executable
    result = LatestOnboardResult(
        ticker=ticker_key,
        allowlist_guidance=allowlist_guidance(ticker_key, configured_tickers),
    )

    def _ensure_book() -> None:
        try:
            book_config = MonitorConfig(
                repo_root=Path(repo_root),
                database_path=Path(repo_root)
                / "services"
                / "earnings_monitor"
                / "state"
                / "monitor.sqlite3",
                inbox_path=Path(repo_root)
                / "earnings-scraper-main"
                / "earnings-scraper-main"
                / "inbox",
                tickers=tuple(configured_tickers) or (ticker_key,),
            )
            integration = ensure_ticker_in_book(
                ticker=ticker_key,
                config=book_config,
                state=state,
                seed_tickers=configured_tickers or book_config.tickers,
            )
            result.steps.append(
                {
                    "step": "ticker_book",
                    "added": integration.added,
                    "n": len(integration.tickers),
                }
            )
            result.allowlist_guidance = allowlist_guidance(
                ticker_key, integration.tickers
            )
        except Exception as exc:  # noqa: BLE001
            result.steps.append({"step": "ticker_book", "error": str(exc)})

    if _panel_exists(Path(repo_root), ticker_key):
        _ensure_book()
        result.status = "already_present"
        periods = discover_on_disk_periods(Path(repo_root), ticker_key)
        result.fiscal_period = periods[-1] if periods else None
        return result

    on_disk = discover_on_disk_periods(Path(repo_root), ticker_key)
    period: str | None = on_disk[-1] if on_disk else None

    if period is None:
        if str(sn) not in sys.path:
            sys.path.insert(0, str(sn))
        from quartr_history_import import import_company_history  # type: ignore

        start = current - timedelta(days=max(30, int(lookback_days)))
        if dry_run:
            result.steps.append(
                {
                    "step": "quartr_latest_import",
                    "dry_run": True,
                    "start": start.isoformat(),
                    "end": current.isoformat(),
                }
            )
            result.status = "dry_run"
            return result

        try:
            imported = import_company_history(
                ticker_key,
                start=start,
                end=current,
                out_dir=sn / "transcripts_raw",
                layout="flat",
                latest_only=True,
            )
        except Exception as exc:  # noqa: BLE001
            result.status = "failed"
            result.error = f"Quartr latest import failed: {exc}"
            return result

        result.company_id = imported.company_id
        result.steps.append(
            {
                "step": "quartr_latest_import",
                "events_seen": imported.events_seen,
                "periods": imported.periods,
                "errors": list(imported.errors)[:5],
                "written": [
                    {
                        "period": item.fiscal_period,
                        "path": str(item.path),
                        "skipped": item.skipped,
                        "reason": item.reason,
                    }
                    for item in imported.written
                ],
            }
        )
        kept = [
            item
            for item in imported.written
            if item.fiscal_period and (not item.skipped or item.reason == "exists")
        ]
        if not kept:
            result.status = "pending_transcript"
            result.error = (
                f"No recent Quartr transcript for {ticker_key} "
                f"(events_seen={imported.events_seen})."
            )
            return result
        period = kept[0].fiscal_period

    result.fiscal_period = period
    assert period is not None

    # First-Print style overlay: empty prior, single output quarter.
    overlay = write_company_overlay(
        Path(repo_root),
        ticker=ticker_key,
        company_name=name,
        prior_quarters=[],
        output_quarters=[period],
        estpermid=None,
        isin=None,
        barra_id=None,
    )
    register_overlay_profile(Path(repo_root), ticker_key)
    result.steps.append({"step": "write_overlay", "path": str(overlay), "period": period})

    calendars = Path(repo_root) / "config" / "fiscal_calendars.yaml"
    try:
        wrote = ensure_fiscal_calendar_entry(
            calendars,
            ticker_key,
            calendar_type="calendar_fiscal",
        )
        result.steps.append({"step": "fiscal_calendar", "written": wrote})
    except Exception as exc:  # noqa: BLE001
        result.steps.append({"step": "fiscal_calendar", "error": str(exc)})

    _ensure_book()

    try:
        if not skip_quant:
            step = runner(
                [py, str(sn / "single_company_extractor.py"), "--ticker", ticker_key],
                cwd=Path(repo_root),
                dry_run=False,
            )
            step["step"] = "single_company_extractor"
            result.steps.append(step)
            step = runner(
                [py, str(sn / "narrative_zscore.py"), "--ticker", ticker_key],
                cwd=Path(repo_root),
                dry_run=False,
            )
            step["step"] = "narrative_zscore"
            result.steps.append(step)

        if not skip_llm:
            pipeline = sn / "run_company_pipeline.py"
            step = runner(
                [
                    py,
                    str(pipeline),
                    "--ticker",
                    ticker_key,
                    "--batch",
                    "--skip-quant",
                    "--no-prior",
                ],
                cwd=Path(repo_root),
                dry_run=False,
            )
            step["step"] = "run_company_pipeline_batch"
            result.steps.append(step)

        step = runner(
            [
                py,
                str(sn / "build_feature_panel.py"),
                "--ticker",
                ticker_key,
                "--from-registry",
                "--include-quarters",
                period,
            ],
            cwd=Path(repo_root),
            dry_run=False,
        )
        step["step"] = "build_feature_panel"
        result.steps.append(step)
        result.steps.append(
            {
                "step": "history_import_handoff",
                "note": (
                    "Refresh the full monitor dataset after micro-onboard "
                    "(do not import a single ticker alone — it overwrites the book)."
                ),
            }
        )

        result.status = "latest_call_onboarded"
    except OnboardError as exc:
        result.status = "failed"
        result.error = str(exc)
    except Exception as exc:  # noqa: BLE001
        LOG.exception("latest-call onboard failed for %s", ticker_key)
        result.status = "failed"
        result.error = str(exc)
    return result
