"""Host orchestrator: watchlist + calendar publish + concurrent live dispatch."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence

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


def _parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


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
    if args.watchlist_action == "sync":
        from .automation_watchlist import sync_entries
        from .config import MonitorConfig
        from .eligibility import monitored_universe_tickers

        config = MonitorConfig.from_env(repo_root=repo_root)
        universe = monitored_universe_tickers(config)
        added, removed = sync_entries(watchlist, universe)
        if not args.dry_run:
            save_watchlist_atomic(path, watchlist)
        print(
            json.dumps(
                {
                    "dry_run": args.dry_run,
                    "path": str(path),
                    "universe_size": len(universe),
                    "added": added,
                    "removed": removed,
                    **watchlist.to_document(),
                },
                indent=2,
            )
        )
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


def _quartr_gateway(repo_root: Path):
    """Authenticated Quartr MCP gateway, or a clear instruction to sign in."""
    from .quartr_mcp import QuartrMcpClient, QuartrMcpGateway
    from .quartr_oauth import default_token_path, get_access_token

    token = get_access_token(default_token_path(repo_root))
    return QuartrMcpGateway(QuartrMcpClient(token))


def _fetch_calendar_dumps(
    tickers: Sequence[str], calendar_dir: Path, repo_root: Path
) -> dict[str, int]:
    """Write one dump per ticker. Only rewrites a file when rows came back.

    A ticker that errors or returns nothing keeps its previous dump rather than
    being truncated to an empty list: an empty dump is indistinguishable from
    "this company has no upcoming call" and would silently retract a manifest
    that had already been published.
    """
    gateway = _quartr_gateway(repo_root)
    calendar_dir.mkdir(parents=True, exist_ok=True)
    total = 0
    written = 0
    for ticker in tickers:
        rows = list(gateway.list_events(ticker=ticker))
        if not rows:
            LOG.info("No Quartr rows for %s; keeping any existing dump", ticker)
            continue
        path = calendar_dir / f"{ticker.strip().upper()}.json"
        path.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        total += len(rows)
        written += 1
    return {"rows": total, "tickers": written}


def cmd_quartr(args: argparse.Namespace) -> int:
    repo_root = (args.repo_root or Path.cwd()).resolve()
    from .quartr_oauth import (
        QuartrAuthError,
        default_token_path,
        get_access_token,
        interactive_login,
        load_tokens,
    )

    token_path = default_token_path(repo_root)
    try:
        if args.quartr_action == "login":
            tokens = interactive_login(token_path, port=args.port)
            print(
                json.dumps(
                    {
                        "connected": True,
                        "token_path": str(token_path),
                        "has_refresh_token": bool(tokens.refresh_token),
                    },
                    indent=2,
                )
            )
            return 0
        if args.quartr_action == "status":
            tokens = load_tokens(token_path)
            print(
                json.dumps(
                    {
                        "token_path": str(token_path),
                        "connected": bool(tokens.refresh_token),
                        "access_token_expired": tokens.expired,
                        "expires_at": tokens.expires_at,
                    },
                    indent=2,
                )
            )
            return 0 if tokens.refresh_token else 1
        if args.quartr_action == "tools":
            from .quartr_mcp import QuartrMcpClient, resolve_events_tool

            client = QuartrMcpClient(get_access_token(token_path))
            tools = client.list_tools()
            names = sorted(str(t.get("name") or "") for t in tools)
            try:
                chosen = resolve_events_tool(tools)
            except Exception as exc:  # noqa: BLE001
                chosen = f"<unresolved: {exc}>"
            print(
                json.dumps(
                    {"count": len(names), "events_tool": chosen, "tools": names},
                    indent=2,
                )
            )
            return 0
    except QuartrAuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
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
    if args.source == "mcp":
        # Land MCP rows as dumps first, then publish from disk exactly as the
        # file-based path does. Publishing straight from a live gateway would
        # bypass the code the tests cover and leave no audit trail of what
        # Quartr actually said on the day an event was armed.
        try:
            fetched = _fetch_calendar_dumps(tickers, calendar_dir, repo_root)
        except Exception as exc:  # noqa: BLE001 - reported via host health
            print(f"error: Quartr fetch failed: {exc}", file=sys.stderr)
            write_host_health(
                defaults["health"],
                job="calendar",
                ok=False,
                started_at=started,
                finished_at=datetime.now(UTC),
                counts={"tickers": len(tickers)},
                failures=[{"error": "quartr_fetch_failed", "detail": str(exc)}],
            )
            return 2
        print(
            f"Fetched {fetched['rows']} rows for {fetched['tickers']} tickers "
            f"into {calendar_dir}"
        )
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
    # Re-verification is only useful if a moved date is visible. Calls inside
    # the attention window are separated out because a change there is the one
    # an operator may need to act on today.
    attention_by = datetime.now(UTC) + timedelta(days=args.verify_within_days)
    moved = [item for item in published if item.rescheduled]
    imminent = [
        item
        for item in moved
        if _parse_iso_utc(item.call_at) is not None
        and _parse_iso_utc(item.call_at) <= attention_by
    ]
    for item in moved:
        print(
            f"SCHEDULE CHANGED {item.ticker} {item.fiscal_period}: "
            f"{item.previous_call_at} -> {item.call_at}"
        )
    if imminent:
        failures.append(
            {
                "error": "schedule_changed_within_window",
                "days": args.verify_within_days,
                "events": [
                    f"{i.ticker} {i.fiscal_period} {i.previous_call_at}->{i.call_at}"
                    for i in imminent
                ],
            }
        )
    if not tickers:
        failures.append({"error": "empty_publish_universe", "detail": "watchlist∩overlays empty"})
    payload: dict[str, Any] = {
        "tickers": list(tickers),
        "published": [item.__dict__ for item in published],
        "schedule_changes": [
            {
                "ticker": i.ticker,
                "fiscal_period": i.fiscal_period,
                "from": i.previous_call_at,
                "to": i.call_at,
                "within_attention_window": i in imminent,
            }
            for i in moved
        ],
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
    sync_p = wl_sub.add_parser("sync", help="Match membership to onboarded companies")
    sync_p.add_argument("--dry-run", action="store_true")
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
    cal.add_argument(
        "--source",
        choices=("dumps", "mcp"),
        default="dumps",
        help="dumps = read existing JSON; mcp = fetch from Quartr first",
    )
    cal.add_argument(
        "--verify-within-days",
        type=int,
        default=7,
        help="flag a moved call this many days out as needing attention",
    )

    q = sub.add_parser("quartr", help="Connect/inspect the Quartr MCP connection")
    q_sub = q.add_subparsers(dest="quartr_action", required=True)
    login_p = q_sub.add_parser("login", help="One-time browser sign-in")
    login_p.add_argument("--port", type=int, default=0)
    q_sub.add_parser("status", help="Show whether Quartr is connected")
    q_sub.add_parser("tools", help="List Quartr MCP tools and the events tool")

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
    if args.command == "quartr":
        return cmd_quartr(args)
    if args.command == "calendar":
        return cmd_calendar(args)
    if args.command == "live":
        return cmd_live(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
