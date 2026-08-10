"""Regenerate Rank IC + consolidated feature-panel HTML for the Roz book.

After a successful post_call the monitor marks the research book dirty.
This module (CLI / Compose research-regen role) regenerates the HTML that
Signal research and Consolidated tabs embed — without blocking email or
event COMPLETE transitions.
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .config import MonitorConfig
from .state import OperationalState

LOG = logging.getLogger(__name__)


# #region agent log
def _agent_debug_log(
    location: str,
    message: str,
    data: dict,
    *,
    hypothesis_id: str,
    run_id: str = "pre-fix",
) -> None:
    import json

    payload = {
        "sessionId": "059d80",
        "timestamp": int(time.time() * 1000),
        "location": location,
        "message": message,
        "data": data,
        "hypothesisId": hypothesis_id,
        "runId": run_id,
    }
    for root in (Path.cwd(), Path(__file__).resolve().parents[2]):
        log_path = root / "debug-059d80.log"
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload) + "\n")
            break
        except OSError:
            continue


# #endregion


@dataclass(frozen=True)
class RegenCommandResult:
    name: str
    command: tuple[str, ...]
    returncode: int
    duration_seconds: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0


@dataclass(frozen=True)
class RegenRunResult:
    triggered_by: str
    started_at: str
    finished_at: str
    commands: tuple[RegenCommandResult, ...]
    skipped: bool = False
    skip_reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.skipped or all(item.ok for item in self.commands)


def _structured_narrative_dir(repo_root: Path) -> Path:
    return repo_root / "Structured Narrative"


def build_rank_ic_command(
    config: MonitorConfig,
    *,
    python: str | None = None,
    tickers: Sequence[str] | None = None,
    fast_regen: bool = True,
) -> list[str]:
    """Build evaluate_narrative_signals argv for dashboard research-regen.

    ``fast_regen`` (default True) skips leave-one-ticker jackknife and lowers
    bootstrap counts. Profiling showed jackknife dominates at book size ≥ ~10:
    ~22 held-out ``evaluate_signals`` passes per horizon × 5 horizons ≈ 93%% of
    Rank IC wall time on a 22-name book.
    """
    script = _structured_narrative_dir(config.repo_root) / "evaluate_narrative_signals.py"
    book = tuple(tickers) if tickers is not None else config.tickers
    cmd = [
        python or sys.executable,
        str(script),
        "--tickers",
        *book,
        "--min-calendar-quarter",
        config.research_min_calendar_quarter,
    ]
    if fast_regen:
        cmd.extend(
            [
                "--no-jackknife",
                "--agreement-bootstrap",
                "500",
                "--primary-hypothesis-bootstrap",
                "500",
            ]
        )
    return cmd


def build_consolidated_command(
    config: MonitorConfig,
    *,
    python: str | None = None,
) -> list[str]:
    script = (
        _structured_narrative_dir(config.repo_root) / "build_consolidated_panel_report.py"
    )
    return [
        python or sys.executable,
        str(script),
        "--sector",
        config.research_sector,
        "--min-calendar-quarter",
        config.research_min_calendar_quarter,
    ]


def _run_command(name: str, command: Sequence[str], *, cwd: Path) -> RegenCommandResult:
    started = time.perf_counter()
    LOG.info("Running %s: %s", name, " ".join(command))
    # #region agent log
    _agent_debug_log(
        "research_regen.py:_run_command:start",
        "regen subprocess starting",
        {
            "name": name,
            "cwd": str(cwd),
            "ticker_arg_count": sum(
                1 for i, part in enumerate(command) if i and command[i - 1] == "--tickers"
            ),
            "argv_len": len(command),
        },
        hypothesis_id="A",
    )
    # #endregion
    completed = subprocess.run(list(command), cwd=str(cwd), check=False)
    duration = time.perf_counter() - started
    if completed.returncode != 0:
        LOG.error("%s failed with exit code %s", name, completed.returncode)
    else:
        LOG.info("%s finished in %.1fs", name, duration)
    # #region agent log
    _agent_debug_log(
        "research_regen.py:_run_command:done",
        "regen subprocess finished",
        {
            "name": name,
            "duration_seconds": round(duration, 3),
            "returncode": int(completed.returncode),
        },
        hypothesis_id="A" if name == "evaluate_narrative_signals" else "B",
    )
    # #endregion
    return RegenCommandResult(
        name=name,
        command=tuple(command),
        returncode=int(completed.returncode),
        duration_seconds=duration,
    )


def regenerate_research_book(
    config: MonitorConfig,
    *,
    triggered_by: str = "manual",
    python: str | None = None,
    tickers: Sequence[str] | None = None,
    fast_regen: bool = True,
) -> RegenRunResult:
    """Run Rank IC then consolidated panel for the configured book."""
    sn_dir = _structured_narrative_dir(config.repo_root)
    if not sn_dir.is_dir():
        raise FileNotFoundError(f"Structured Narrative directory missing: {sn_dir}")
    book = tuple(tickers) if tickers is not None else config.tickers
    # #region agent log
    _agent_debug_log(
        "research_regen.py:regenerate_research_book",
        "research book regen scope",
        {
            "triggered_by": triggered_by,
            "book_size": len(book),
            "tickers": list(book),
            "min_calendar_quarter": config.research_min_calendar_quarter,
            "sector": config.research_sector,
            "fast_regen": fast_regen,
        },
        hypothesis_id="A",
        run_id="post-fix" if fast_regen else "pre-fix",
    )
    # #endregion
    started = datetime.now(timezone.utc)
    commands: list[RegenCommandResult] = [
        _run_command(
            "evaluate_narrative_signals",
            build_rank_ic_command(
                config, python=python, tickers=book, fast_regen=fast_regen
            ),
            cwd=sn_dir,
        )
    ]
    # Do not refresh consolidated HTML if Rank IC failed — keeps artifacts
    # consistent and avoids a long wasted panel rebuild.
    if commands[0].ok:
        commands.append(
            _run_command(
                "build_consolidated_panel_report",
                build_consolidated_command(config, python=python),
                cwd=sn_dir,
            )
        )
    finished = datetime.now(timezone.utc)
    return RegenRunResult(
        triggered_by=triggered_by,
        started_at=started.isoformat(),
        finished_at=finished.isoformat(),
        commands=tuple(commands),
    )


def _dirty_age_seconds(dirty: dict, *, now: datetime) -> float | None:
    marked_at = dirty.get("marked_at")
    if not marked_at:
        return None
    try:
        stamped = datetime.fromisoformat(str(marked_at))
    except ValueError:
        return None
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    return max(0.0, (now - stamped.astimezone(timezone.utc)).total_seconds())


def run_research_regen_once(
    config: MonitorConfig,
    state: OperationalState,
    *,
    force: bool = False,
    honor_debounce: bool = True,
    python: str | None = None,
    runner=None,
    fast_regen: bool = True,
) -> RegenRunResult:
    """Clear dirty (if any) and regenerate, or skip when clean / still debouncing."""
    dirty = state.research_book_dirty()
    now = datetime.now(timezone.utc)
    if not force:
        if dirty is None:
            return RegenRunResult(
                triggered_by="idle",
                started_at=now.isoformat(),
                finished_at=now.isoformat(),
                commands=(),
                skipped=True,
                skip_reason="not_dirty",
            )
        if honor_debounce and config.research_regen_debounce_seconds > 0:
            age = _dirty_age_seconds(dirty, now=now)
            if age is not None and age < config.research_regen_debounce_seconds:
                return RegenRunResult(
                    triggered_by="debounce",
                    started_at=now.isoformat(),
                    finished_at=now.isoformat(),
                    commands=(),
                    skipped=True,
                    skip_reason=(
                        f"debounce_{config.research_regen_debounce_seconds}s"
                    ),
                )
    # Clear before running so post_calls that land mid-regen re-dirty the book.
    state.clear_research_book_dirty()
    trigger = "force" if force else "dirty"
    if dirty and dirty.get("triggers"):
        trigger = ",".join(str(item) for item in dirty["triggers"][-5:])
    from .ticker_book import resolve_book_tickers, seed_book_if_empty

    seed_book_if_empty(config, state)
    book_tickers = resolve_book_tickers(config, state)
    regenerate = runner or regenerate_research_book
    try:
        if runner is None:
            result = regenerate(
                config,
                triggered_by=trigger,
                python=python,
                tickers=book_tickers,
                fast_regen=fast_regen,
            )
        else:
            # Tests pass a stub that may not accept tickers=.
            result = regenerate(config, triggered_by=trigger, python=python)
    except Exception:
        # Clear happened above; restore dirty so the loop can retry.
        state.mark_research_book_dirty(
            reason="regen_exception",
            trigger=trigger,
            now=now,
        )
        raise
    state.set_meta(
        "research_book_last_regen",
        json.dumps(
            {
                "ok": result.ok,
                "triggered_by": result.triggered_by,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
            },
            sort_keys=True,
        ),
        now=now,
    )
    if not result.ok:
        # Re-mark dirty so the loop retries after a failed regen.
        state.mark_research_book_dirty(
            reason="regen_failed",
            trigger=result.triggered_by,
            now=now,
        )
    return result


def run_research_regen_loop(config: MonitorConfig, state: OperationalState) -> None:
    """Poll the dirty flag and regenerate when due."""
    from .ticker_book import seed_book_if_empty

    idle = max(1, int(config.research_regen_idle_seconds))
    book = seed_book_if_empty(config, state)
    LOG.info(
        "Research regen loop started (idle=%ss debounce=%ss sector=%s "
        "min_cal=%s book_tickers=%s)",
        idle,
        config.research_regen_debounce_seconds,
        config.research_sector,
        config.research_min_calendar_quarter,
        len(book),
    )
    while True:
        result = run_research_regen_once(config, state, force=False, honor_debounce=True)
        if result.skipped:
            time.sleep(idle)
            continue
        if result.ok:
            LOG.info("Research book regenerated (%s)", result.triggered_by)
        else:
            LOG.error("Research book regen failed; will retry after idle")
        time.sleep(idle)
