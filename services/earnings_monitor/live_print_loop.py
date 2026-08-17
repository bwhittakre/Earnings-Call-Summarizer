"""Host live-print loop: wait for a fresh MCP dump, then sweep live→final.

Designed for Cursor Automation near ``call_at``. Calendar publisher's
``--list-due`` (or :func:`calendar_publish.list_due_sweep_targets`) emits the
worklist of event ids to feed here.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .quartr_sweep import (
    JsonDumpGateway,
    SweepTarget,
    run_sweep_loop,
    write_sweep_bundle,
)

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class DumpWaitResult:
    path: str
    waited_seconds: float
    mtime_ns: int


def wait_for_fresh_dump(
    path: Path | str,
    *,
    min_mtime_ns: int | None = None,
    timeout_seconds: float = 3600.0,
    poll_seconds: float = 5.0,
) -> DumpWaitResult:
    """Block until ``path`` exists and (optionally) is newer than ``min_mtime_ns``."""
    target = Path(path)
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    started = time.monotonic()
    deadline = started + timeout_seconds
    while True:
        if target.is_file():
            mtime_ns = target.stat().st_mtime_ns
            if min_mtime_ns is None or mtime_ns > min_mtime_ns:
                return DumpWaitResult(
                    path=str(target),
                    waited_seconds=time.monotonic() - started,
                    mtime_ns=mtime_ns,
                )
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"timed out after {timeout_seconds}s waiting for fresh dump at {target}"
            )
        time.sleep(poll_seconds)


def run_live_print_loop(
    *,
    event_id: str,
    ticker: str,
    fiscal_period: str,
    dump_path: Path | str,
    inbox: Path | str,
    source_url: str | None = None,
    wait_timeout_seconds: float = 3600.0,
    wait_poll_seconds: float = 5.0,
    require_newer_than_mtime_ns: int | None = None,
    sweep_interval_seconds: float = 30.0,
    sweep_max_minutes: float | None = None,
    once: bool = False,
    force_final: bool = False,
) -> dict[str, Any]:
    """Wait for MCP dump freshness, then run quartr_sweep live→final."""
    waited = wait_for_fresh_dump(
        dump_path,
        min_mtime_ns=require_newer_than_mtime_ns,
        timeout_seconds=wait_timeout_seconds,
        poll_seconds=wait_poll_seconds,
    )
    gateway = JsonDumpGateway(waited.path)
    target = SweepTarget(
        event_id=str(event_id),
        ticker=ticker,
        fiscal_period=fiscal_period,
        inbox=Path(inbox),
        source_url=source_url,
    )
    if once:
        sweep = write_sweep_bundle(gateway, target, force_final=force_final)
    else:
        sweep = run_sweep_loop(
            gateway,
            target,
            interval_seconds=sweep_interval_seconds,
            max_minutes=sweep_max_minutes,
            force_final_on_exit=True,
        )
    return {
        "dump": waited.__dict__,
        "sweep": sweep,
        "event_id": str(event_id),
        "ticker": ticker.strip().upper(),
        "fiscal_period": fiscal_period.strip().upper(),
        "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.earnings_monitor.live_print_loop",
        description=(
            "Wait for a fresh Quartr MCP transcript dump, then sweep live→final "
            "into the monitor inbox. Use calendar_publish --list-due for dispatch."
        ),
    )
    parser.add_argument("--event-id", required=True)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--period", required=True, help="Fiscal period, e.g. FY2026-Q2")
    parser.add_argument("--dump", required=True, type=Path, help="MCP read_transcript JSON path")
    parser.add_argument("--inbox", required=True, type=Path)
    parser.add_argument("--source-url", default=None)
    parser.add_argument(
        "--wait-timeout-seconds",
        type=float,
        default=3600.0,
        help="Max seconds to wait for dump freshness (default 3600)",
    )
    parser.add_argument(
        "--wait-poll-seconds",
        type=float,
        default=5.0,
        help="Poll interval while waiting for dump (default 5)",
    )
    parser.add_argument(
        "--require-newer-than-mtime-ns",
        type=int,
        default=None,
        help="Require dump mtime_ns strictly greater than this value",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Single sweep write (no live→final poll loop)",
    )
    parser.add_argument(
        "--final",
        action="store_true",
        help="With --once, force status=final",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=30.0,
        help="Sweep loop interval (default 30)",
    )
    parser.add_argument(
        "--max-minutes",
        type=float,
        default=None,
        help="Stop sweep loop after N minutes and force final",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)
    try:
        result = run_live_print_loop(
            event_id=str(args.event_id),
            ticker=args.ticker,
            fiscal_period=args.period,
            dump_path=args.dump,
            inbox=args.inbox,
            source_url=args.source_url,
            wait_timeout_seconds=args.wait_timeout_seconds,
            wait_poll_seconds=args.wait_poll_seconds,
            require_newer_than_mtime_ns=args.require_newer_than_mtime_ns,
            sweep_interval_seconds=args.interval_seconds,
            sweep_max_minutes=args.max_minutes,
            once=bool(args.once),
            force_final=bool(args.final),
        )
    except TimeoutError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
