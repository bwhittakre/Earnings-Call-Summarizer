"""Host orchestrator: watchlist + calendar publish + concurrent live dispatch."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .automation_watchlist import (
    default_watchlist_path,
    load_watchlist,
    prune_event_manifests,
    save_watchlist_atomic,
)
from .calendar_publish import (
    MergedJsonDirGateway,
    list_due_sweep_targets,
    publish_calendar,
    resolve_publish_tickers,
    write_due_worklist,
)
from .eligibility import default_overlay_dir
from .live_print_dispatch import load_worklist, run_dispatch
from .ops_health import default_host_health_path, write_host_health

LOG = logging.getLogger(__name__)
UTC = timezone.utc

DEFAULT_HOST_ROOT = Path("host_quartr")


def _default_paths(repo_root: Path) -> dict[str, Path]:
    host = repo_root / DEFAULT_HOST_ROOT
    return {
        "calendar_dir": host / "calendar",
        "dumps_dir": host / "transcripts",
        "worklist": host / "worklists" / "due_sweep.json",
        "health": default_host_health_path(repo_root),
        "events_dir": repo_root
        / "earnings-scraper-main"
        / "earnings-scraper-main"
        / "inbox"
        / "events",
        "inbox": repo_root
        / "earnings-scraper-main"
        / "earnings-scraper-main"
        / "inbox",
        "watchlist": default_watchlist_path(repo_root),
    }


def cmd_watchlist(args: argparse.Namespace) -> int:
    repo_root = (args.repo_root or Path.cwd()).resolve()
    path = Path(args.watchlist) if args.watchlist else default_watchlist_path(repo_root)
    watchlist = load_watchlist(path)
    if args.watchlist_action == "list":
        print(json.dumps({"path": str(path), **watchlist.to_document()}, indent=2))
        return 0
    if args.watchlist_action == "add":
        changed = watchlist.add_entry(args.ticker, args.period)
        save_watchlist_atomic(path, watchlist)
        print(
            json.dumps(
                {"changed": changed, "path": str(path), **watchlist.to_document()},
                indent=2,
            )
        )
        return 0
    if args.watchlist_action == "remove":
        changed = watchlist.remove_entry(args.ticker, args.period)
        save_watchlist_atomic(path, watchlist)
        pruned: list[str] = []
        if args.prune_manifests:
            events_dir = args.events_dir or _default_paths(repo_root)["events_dir"]
            pruned = prune_event_manifests(
                events_dir, ticker=args.ticker, period=args.period
            )
        print(
            json.dumps(
                {
                    "changed": changed,
                    "path": str(path),
                    "pruned_manifests": pruned,
                    **watchlist.to_document(),
                },
                indent=2,
            )
        )
        return 0
    return 2


def cmd_calendar(args: argparse.Namespace) -> int:
    started = datetime.now(UTC)
    repo_root = (args.repo_root or Path.cwd()).resolve()
    defaults = _default_paths(repo_root)
    calendar_dir = Path(args.calendar_dir or defaults["calendar_dir"])
    events_dir = Path(args.events_dir or defaults["events_dir"])
    worklist_out = Path(args.worklist_out or defaults["worklist"])
    overlay_dir = Path(args.overlay_dir) if args.overlay_dir else default_overlay_dir(repo_root)
    wl_path = Path(args.watchlist) if args.watchlist else defaults["watchlist"]
    watchlist = None if args.no_watchlist else load_watchlist(wl_path)

    tickers_arg = (
        [t for t in args.tickers.split(",") if t.strip()] if args.tickers else None
    )
    tickers = resolve_publish_tickers(
        tickers=tickers_arg,
        repo_root=repo_root,
        overlay_dir=overlay_dir,
        sector=args.sector,
        watchlist=watchlist,
    )
    failures: list[dict[str, Any]] = []
    if not calendar_dir.is_dir():
        print(f"error: calendar dump dir not found: {calendar_dir}", file=sys.stderr)
        write_host_health(
            defaults["health"],
            job="calendar",
            ok=False,
            started_at=started,
            finished_at=datetime.now(UTC),
            counts={"tickers": len(tickers)},
            failures=[{"error": "calendar_dir_missing", "path": str(calendar_dir)}],
        )
        return 2
    gateway = MergedJsonDirGateway(calendar_dir)
    published = publish_calendar(
        gateway,
        tickers=tickers,
        events_dir=events_dir,
        horizon_days=args.horizon_days,
        dry_run=bool(args.dry_run),
        watchlist=watchlist,
    )
    due = list_due_sweep_targets(
        gateway,
        tickers=tickers,
        within_hours=args.due_within_hours,
        watchlist=watchlist,
    )
    wrote = write_due_worklist(worklist_out, due)
    if not tickers:
        failures.append({"error": "empty_publish_universe", "detail": "watchlist∩overlays empty"})
    payload: dict[str, Any] = {
        "tickers": list(tickers),
        "published": [item.__dict__ for item in published],
        "due_sweep": [item.__dict__ for item in due],
        "worklist_out": str(wrote),
        "events_dir": str(events_dir),
        "calendar_dir": str(calendar_dir),
        "dry_run": bool(args.dry_run),
        "ok": not failures,
    }
    write_host_health(
        defaults["health"],
        job="calendar",
        ok=not failures,
        started_at=started,
        finished_at=datetime.now(UTC),
        counts={
            "tickers": len(tickers),
            "published": len(published),
            "due": len(due),
        },
        failures=failures,
        extra={"worklist_out": str(wrote)},
    )
    print(json.dumps(payload, indent=2))
    return 1 if failures else 0


def cmd_live(args: argparse.Namespace) -> int:
    started = datetime.now(UTC)
    repo_root = (args.repo_root or Path.cwd()).resolve()
    defaults = _default_paths(repo_root)
    worklist_path = Path(args.worklist_file or defaults["worklist"])
    dumps_dir = Path(args.dumps_dir or defaults["dumps_dir"])
    inbox = Path(args.inbox or defaults["inbox"])
    wl_path = Path(args.watchlist) if args.watchlist else defaults["watchlist"]
    watchlist = None if args.no_watchlist else load_watchlist(wl_path)
    if not worklist_path.is_file():
        print(f"error: worklist not found: {worklist_path}", file=sys.stderr)
        write_host_health(
            defaults["health"],
            job="live",
            ok=False,
            started_at=started,
            finished_at=datetime.now(UTC),
            failures=[{"error": "worklist_missing", "path": str(worklist_path)}],
        )
        return 2
    targets = load_worklist(worklist_path)
    # Production default: loop live→final. --once / --final are escape hatches.
    use_loop = bool(args.loop) or not bool(args.once)
    if args.final and not args.once:
        # --final without --once: treat as once+final escape hatch.
        use_loop = False
    once = not use_loop
    require_dump: bool | None
    if args.require_dump:
        require_dump = True
    elif args.allow_missing_dump:
        require_dump = False
    else:
        require_dump = None  # hard-fail only near call_at
    results = run_dispatch(
        targets,
        dumps_dir=dumps_dir,
        inbox=inbox,
        watchlist=watchlist,
        max_workers=args.max_workers,
        once=once,
        force_final=bool(args.final),
        wait_timeout_seconds=args.wait_timeout_seconds,
        wait_poll_seconds=args.wait_poll_seconds,
        sweep_interval_seconds=args.interval_seconds,
        sweep_max_minutes=args.max_minutes,
        require_dump=require_dump,
        max_dump_age_minutes=(
            None if args.max_dump_age_minutes <= 0 else args.max_dump_age_minutes
        ),
    )
    hard_fail = any(not row.ok for row in results)
    failures = [
        {
            "event_id": row.event_id,
            "ticker": row.ticker,
            "fiscal_period": row.fiscal_period,
            "error": row.error,
            "skipped_reason": row.skipped_reason,
        }
        for row in results
        if not row.ok
    ]
    write_host_health(
        defaults["health"],
        job="live",
        ok=not hard_fail,
        started_at=started,
        finished_at=datetime.now(UTC),
        counts={
            "targets": len(targets),
            "ok": sum(1 for row in results if row.ok),
            "failed": len(failures),
            "mode": "loop" if use_loop else "once",
            "force_final": bool(args.final),
        },
        failures=failures,
        extra={
            "worklist": str(worklist_path),
            "dumps_dir": str(dumps_dir),
        },
    )
    print(
        json.dumps(
            {
                "worklist": str(worklist_path),
                "dumps_dir": str(dumps_dir),
                "inbox": str(inbox),
                "targets": len(targets),
                "mode": "loop" if use_loop else "once",
                "force_final": bool(args.final),
                "results": [row.__dict__ for row in results],
                "ok": not hard_fail,
                "health": str(defaults["health"]),
            },
            indent=2,
        )
    )
    return 1 if hard_fail else 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.earnings_monitor.host_automation",
        description=(
            "Host automation orchestrator: watchlist membership, calendar publish, "
            "and concurrent live dispatch."
        ),
    )
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--watchlist", type=Path, default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    wl = sub.add_parser("watchlist", help="Add/remove/list automation membership")
    wl_sub = wl.add_subparsers(dest="watchlist_action", required=True)
    wl_sub.add_parser("list")
    add_p = wl_sub.add_parser("add")
    add_p.add_argument("--ticker", required=True)
    add_p.add_argument("--period", default=None)
    rem_p = wl_sub.add_parser("remove")
    rem_p.add_argument("--ticker", required=True)
    rem_p.add_argument("--period", default=None)
    rem_p.add_argument("--prune-manifests", action="store_true")
    rem_p.add_argument("--events-dir", type=Path, default=None)

    cal = sub.add_parser("calendar", help="Publish manifests + due worklist from dump dir")
    cal.add_argument("--calendar-dir", type=Path, default=None)
    cal.add_argument("--events-dir", type=Path, default=None)
    cal.add_argument("--worklist-out", type=Path, default=None)
    cal.add_argument("--overlay-dir", type=Path, default=None)
    cal.add_argument("--tickers", default="")
    cal.add_argument("--sector", default="xlk_tech")
    cal.add_argument("--horizon-days", type=int, default=30)
    cal.add_argument("--due-within-hours", type=float, default=6.0)
    cal.add_argument("--dry-run", action="store_true")
    cal.add_argument("--no-watchlist", action="store_true")

    live = sub.add_parser(
        "live",
        help="Concurrent live→final dispatch from worklist (default: --loop)",
    )
    live.add_argument("--worklist-file", type=Path, default=None)
    live.add_argument("--dumps-dir", type=Path, default=None)
    live.add_argument("--inbox", type=Path, default=None)
    live.add_argument("--max-workers", type=int, default=4)
    live.add_argument(
        "--loop",
        action="store_true",
        help="Poll live→final (default when --once/--final not set)",
    )
    live.add_argument(
        "--once",
        action="store_true",
        help="Single sweep only (escape hatch)",
    )
    live.add_argument(
        "--final",
        action="store_true",
        help="Force FINAL write (skips LIVE; escape hatch, implies once)",
    )
    live.add_argument("--wait-timeout-seconds", type=float, default=60.0)
    live.add_argument("--wait-poll-seconds", type=float, default=1.0)
    live.add_argument("--interval-seconds", type=float, default=30.0)
    live.add_argument("--max-minutes", type=float, default=None)
    live.add_argument(
        "--require-dump",
        action="store_true",
        help="Hard-fail every missing dump (not only near-call)",
    )
    live.add_argument(
        "--allow-missing-dump",
        action="store_true",
        help="Soft-skip missing dumps even near call_at",
    )
    live.add_argument(
        "--max-dump-age-minutes",
        type=float,
        default=45.0,
        help="Near-call dump mtime older than this → stale_dump (0 disables)",
    )
    live.add_argument("--no-watchlist", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)
    if args.command == "watchlist":
        return cmd_watchlist(args)
    if args.command == "calendar":
        return cmd_calendar(args)
    if args.command == "live":
        return cmd_live(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
