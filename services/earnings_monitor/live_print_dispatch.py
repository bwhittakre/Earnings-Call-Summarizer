"""Concurrent live-print dispatcher over a due worklist + per-event dumps."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .automation_watchlist import (
    Watchlist,
    default_watchlist_path,
    load_watchlist,
)
from .calendar_publish import DueSweepTarget
from .live_print_loop import run_live_print_loop

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class DispatchResult:
    event_id: str
    ticker: str
    fiscal_period: str
    ok: bool
    skipped_reason: str | None = None
    error: str | None = None
    sweep: dict[str, Any] | None = None


def load_worklist(path: Path | str) -> list[DueSweepTarget]:
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if isinstance(payload, dict):
        rows = payload.get("due_sweep") or payload.get("targets") or payload.get("items")
        if rows is None and payload.get("event_id"):
            rows = [payload]
    elif isinstance(payload, list):
        rows = payload
    else:
        raise ValueError(f"unrecognized worklist shape: {path}")
    if not isinstance(rows, list):
        raise ValueError("worklist targets must be a list")
    targets: list[DueSweepTarget] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or row.get("provider_event_id") or "").strip()
        ticker = str(row.get("ticker") or "").strip().upper()
        period = str(row.get("fiscal_period") or row.get("period") or "").strip().upper()
        if not event_id or not ticker or not period:
            continue
        targets.append(
            DueSweepTarget(
                event_id=event_id,
                ticker=ticker,
                fiscal_period=period,
                call_at=str(row.get("call_at") or ""),
                source_url=row.get("source_url"),
                is_live_hint=bool(row.get("is_live_hint")),
            )
        )
    return targets


def dump_path_for(dumps_dir: Path, event_id: str) -> Path:
    return Path(dumps_dir) / f"{event_id}.json"


def _dispatch_one(
    target: DueSweepTarget,
    *,
    dumps_dir: Path,
    inbox: Path,
    watchlist: Watchlist | None,
    once: bool,
    force_final: bool,
    wait_timeout_seconds: float,
    wait_poll_seconds: float,
    sweep_interval_seconds: float,
    sweep_max_minutes: float | None,
    require_dump: bool,
) -> DispatchResult:
    if watchlist is not None and not watchlist.is_automated(
        target.ticker, target.fiscal_period
    ):
        return DispatchResult(
            event_id=target.event_id,
            ticker=target.ticker,
            fiscal_period=target.fiscal_period,
            ok=True,
            skipped_reason="not_on_watchlist",
        )
    dump = dump_path_for(dumps_dir, target.event_id)
    if not dump.is_file():
        if require_dump:
            return DispatchResult(
                event_id=target.event_id,
                ticker=target.ticker,
                fiscal_period=target.fiscal_period,
                ok=False,
                error="missing_dump",
                skipped_reason="missing_dump",
            )
        return DispatchResult(
            event_id=target.event_id,
            ticker=target.ticker,
            fiscal_period=target.fiscal_period,
            ok=True,
            skipped_reason="missing_dump",
        )
    try:
        result = run_live_print_loop(
            event_id=target.event_id,
            ticker=target.ticker,
            fiscal_period=target.fiscal_period,
            dump_path=dump,
            inbox=inbox,
            source_url=target.source_url,
            wait_timeout_seconds=wait_timeout_seconds,
            wait_poll_seconds=wait_poll_seconds,
            sweep_interval_seconds=sweep_interval_seconds,
            sweep_max_minutes=sweep_max_minutes,
            once=once,
            force_final=force_final,
        )
        return DispatchResult(
            event_id=target.event_id,
            ticker=target.ticker,
            fiscal_period=target.fiscal_period,
            ok=True,
            sweep=result.get("sweep"),
        )
    except Exception as exc:  # noqa: BLE001
        LOG.exception("dispatch failed event=%s", target.event_id)
        return DispatchResult(
            event_id=target.event_id,
            ticker=target.ticker,
            fiscal_period=target.fiscal_period,
            ok=False,
            error=str(exc),
        )


def run_dispatch(
    targets: list[DueSweepTarget],
    *,
    dumps_dir: Path,
    inbox: Path,
    watchlist: Watchlist | None = None,
    max_workers: int = 4,
    once: bool = True,
    force_final: bool = False,
    wait_timeout_seconds: float = 60.0,
    wait_poll_seconds: float = 1.0,
    sweep_interval_seconds: float = 30.0,
    sweep_max_minutes: float | None = None,
    require_dump: bool = False,
) -> list[DispatchResult]:
    if max_workers < 1:
        raise ValueError("max_workers must be >= 1")
    if not targets:
        return []
    results: list[DispatchResult] = []
    workers = min(max_workers, len(targets))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                _dispatch_one,
                target,
                dumps_dir=Path(dumps_dir),
                inbox=Path(inbox),
                watchlist=watchlist,
                once=once,
                force_final=force_final,
                wait_timeout_seconds=wait_timeout_seconds,
                wait_poll_seconds=wait_poll_seconds,
                sweep_interval_seconds=sweep_interval_seconds,
                sweep_max_minutes=sweep_max_minutes,
                require_dump=require_dump,
            ): target
            for target in targets
        }
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: (row.ticker, row.fiscal_period, row.event_id))
    return results


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.earnings_monitor.live_print_dispatch",
        description=(
            "Dispatch concurrent live_print_loop jobs from a due worklist "
            "and per-event transcript dumps."
        ),
    )
    parser.add_argument("--worklist", type=Path, required=True)
    parser.add_argument("--dumps-dir", type=Path, required=True)
    parser.add_argument("--inbox", type=Path, required=True)
    parser.add_argument(
        "--watchlist",
        type=Path,
        default=None,
        help="Re-filter targets against automation watchlist",
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--max-workers", type=int, default=4)
    parser.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="Single sweep write per event (default)",
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Poll live→final instead of --once",
    )
    parser.add_argument("--final", action="store_true", help="With once, force final")
    parser.add_argument("--wait-timeout-seconds", type=float, default=60.0)
    parser.add_argument("--wait-poll-seconds", type=float, default=1.0)
    parser.add_argument("--interval-seconds", type=float, default=30.0)
    parser.add_argument("--max-minutes", type=float, default=None)
    parser.add_argument(
        "--require-dump",
        action="store_true",
        help="Treat missing dumps as hard failures",
    )
    parser.add_argument(
        "--no-watchlist",
        action="store_true",
        help="Do not filter by automation watchlist",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)
    repo_root = (args.repo_root or Path.cwd()).resolve()
    watchlist: Watchlist | None = None
    if not args.no_watchlist:
        wl_path = args.watchlist or default_watchlist_path(repo_root)
        watchlist = load_watchlist(wl_path)
    targets = load_worklist(args.worklist)
    results = run_dispatch(
        targets,
        dumps_dir=Path(args.dumps_dir),
        inbox=Path(args.inbox),
        watchlist=watchlist,
        max_workers=args.max_workers,
        once=not bool(args.loop),
        force_final=bool(args.final),
        wait_timeout_seconds=args.wait_timeout_seconds,
        wait_poll_seconds=args.wait_poll_seconds,
        sweep_interval_seconds=args.interval_seconds,
        sweep_max_minutes=args.max_minutes,
        require_dump=bool(args.require_dump),
    )
    hard_fail = any(not row.ok for row in results)
    payload = {
        "targets": len(targets),
        "results": [asdict(row) for row in results],
        "ok": not hard_fail,
    }
    print(json.dumps(payload, indent=2))
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
