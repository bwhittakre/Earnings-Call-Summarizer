"""Editable automation watchlist: add/remove companies or quarters anytime."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML is expected in the SN env
    yaml = None  # type: ignore[assignment]

from .providers import EVENT_MANIFEST_SUFFIX

_PERIOD_RE = re.compile(r"^FY\d{4}-Q[1-4]$", re.IGNORECASE)
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")

DEFAULT_WATCHLIST_REL = Path("config") / "automation_watchlist.yaml"


@dataclass(frozen=True)
class WatchlistEntry:
    ticker: str
    period: str | None = None

    def to_dict(self) -> dict[str, str]:
        row: dict[str, str] = {"ticker": self.ticker}
        if self.period:
            row["period"] = self.period
        return row


@dataclass
class Watchlist:
    entries: list[WatchlistEntry] = field(default_factory=list)
    path: Path | None = None

    def iter_tickers(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(entry.ticker for entry in self.entries))

    def is_automated(self, ticker: str, period: str | None = None) -> bool:
        key = ticker.strip().upper()
        period_key = period.strip().upper() if period else None
        for entry in self.entries:
            if entry.ticker != key:
                continue
            if entry.period is None:
                return True
            if period_key is not None and entry.period == period_key:
                return True
        return False

    def add_entry(self, ticker: str, period: str | None = None) -> bool:
        """Add an entry. Returns True when the watchlist changed."""
        entry = _normalize_entry(ticker, period)
        before = [row.to_dict() for row in self.entries]
        if entry.period is None:
            # Ticker-only covers everything; drop redundant period rows.
            self.entries = [row for row in self.entries if row.ticker != entry.ticker]
            self.entries.append(entry)
        else:
            if any(row.ticker == entry.ticker and row.period is None for row in self.entries):
                return False
            if any(
                row.ticker == entry.ticker and row.period == entry.period
                for row in self.entries
            ):
                return False
            self.entries.append(entry)
        return [row.to_dict() for row in self.entries] != before

    def remove_entry(self, ticker: str, period: str | None = None) -> bool:
        """Remove company (all rows) or one quarter. Returns True when changed."""
        key = ticker.strip().upper()
        period_key = period.strip().upper() if period else None
        before = list(self.entries)
        if period_key is None:
            self.entries = [row for row in self.entries if row.ticker != key]
        else:
            self.entries = [
                row
                for row in self.entries
                if not (row.ticker == key and row.period == period_key)
            ]
        return self.entries != before

    def to_document(self) -> dict[str, Any]:
        return {"entries": [entry.to_dict() for entry in self.entries]}


def sync_entries(
    watchlist: Watchlist, tickers: Iterable[str]
) -> tuple[list[str], list[str]]:
    """Make ticker-only membership match ``tickers``. Returns (added, removed).

    Rows carrying an explicit period are left untouched: those are deliberate
    single-quarter pins an operator added by hand, not managed membership.
    """
    desired = {str(t).strip().upper() for t in tickers if str(t).strip()}
    pinned = {row.ticker for row in watchlist.entries if row.period is not None}
    current = {row.ticker for row in watchlist.entries if row.period is None}
    added = sorted(desired - current)
    removed = sorted(current - desired - pinned)
    for ticker in added:
        watchlist.add_entry(ticker)
    for ticker in removed:
        watchlist.entries = [
            row
            for row in watchlist.entries
            if not (row.ticker == ticker and row.period is None)
        ]
    return added, removed


def default_watchlist_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    return Path(root) / DEFAULT_WATCHLIST_REL


def _normalize_entry(ticker: str, period: str | None) -> WatchlistEntry:
    key = ticker.strip().upper()
    if not _TICKER_RE.fullmatch(key):
        raise ValueError(f"invalid ticker: {ticker!r}")
    if period is None or not str(period).strip():
        return WatchlistEntry(ticker=key, period=None)
    period_key = str(period).strip().upper()
    if not _PERIOD_RE.fullmatch(period_key):
        raise ValueError(f"invalid fiscal period: {period!r} (expected FY####-Q#)")
    return WatchlistEntry(ticker=key, period=period_key)


def load_watchlist(path: Path | str | None = None) -> Watchlist:
    """Load watchlist; missing file → empty entries."""
    target = Path(path) if path is not None else default_watchlist_path()
    if not target.is_file():
        return Watchlist(entries=[], path=target)
    text = target.read_text(encoding="utf-8-sig")
    if yaml is None:
        raise RuntimeError("PyYAML is required to load automation_watchlist.yaml")
    payload = yaml.safe_load(text) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"watchlist root must be a mapping: {target}")
    raw_entries = payload.get("entries") or []
    if not isinstance(raw_entries, list):
        raise ValueError("watchlist.entries must be a list")
    entries: list[WatchlistEntry] = []
    for index, item in enumerate(raw_entries):
        if not isinstance(item, dict):
            raise ValueError(f"entries[{index}] must be an object")
        ticker = item.get("ticker")
        if not isinstance(ticker, str):
            raise ValueError(f"entries[{index}].ticker must be a string")
        period = item.get("period")
        if period is not None and not isinstance(period, str):
            raise ValueError(f"entries[{index}].period must be a string or null")
        entries.append(_normalize_entry(ticker, period))
    return Watchlist(entries=entries, path=target)


def save_watchlist_atomic(path: Path | str, watchlist: Watchlist) -> Path:
    if yaml is None:
        raise RuntimeError("PyYAML is required to save automation_watchlist.yaml")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "# Host automation membership (calendar publish + live dispatch).\n"
        "# Empty entries = automate nothing (safe default).\n"
        "# ticker-only: all upcoming earnings quarters for that company.\n"
        "# ticker + period: only that fiscal quarter.\n"
        + yaml.safe_dump(
            watchlist.to_document(),
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
    )
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=destination.parent,
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(body)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    watchlist.path = destination
    return destination


def prune_event_manifests(
    events_dir: Path | str,
    *,
    ticker: str,
    period: str | None = None,
) -> list[str]:
    """Delete matching ``*.event.json`` manifests. Returns deleted paths."""
    root = Path(events_dir)
    if not root.is_dir():
        return []
    key = ticker.strip().upper()
    period_key = period.strip().upper() if period else None
    deleted: list[str] = []
    for path in sorted(root.glob(f"*{EVENT_MANIFEST_SUFFIX}")):
        stem = path.name[: -len(EVENT_MANIFEST_SUFFIX)]
        if period_key is not None:
            if stem == f"{key}-{period_key}":
                path.unlink(missing_ok=True)
                deleted.append(str(path))
            continue
        if stem.startswith(f"{key}-") or stem == key:
            # Ticker-PERIOD.event.json
            if stem.startswith(f"{key}-FY") or stem.upper().startswith(f"{key}-FY"):
                path.unlink(missing_ok=True)
                deleted.append(str(path))
    return deleted


def filter_targets_by_watchlist(
    targets: Iterable[Any],
    watchlist: Watchlist,
) -> list[Any]:
    """Keep objects with ``.ticker`` / ``.fiscal_period`` (or dict keys)."""
    kept: list[Any] = []
    for item in targets:
        if isinstance(item, dict):
            ticker = str(item.get("ticker") or "")
            period = str(item.get("fiscal_period") or item.get("period") or "")
        else:
            ticker = str(getattr(item, "ticker", "") or "")
            period = str(
                getattr(item, "fiscal_period", None)
                or getattr(item, "period", "")
                or ""
            )
        if watchlist.is_automated(ticker, period or None):
            kept.append(item)
    return kept


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.earnings_monitor.automation_watchlist",
        description="List/add/remove automation watchlist entries.",
    )
    parser.add_argument(
        "--watchlist",
        type=Path,
        default=None,
        help=f"Path to YAML (default: {DEFAULT_WATCHLIST_REL})",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repo root for default watchlist path",
    )
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="Print watchlist entries as JSON")
    add_p = sub.add_parser("add", help="Add a company or quarter")
    add_p.add_argument("--ticker", required=True)
    add_p.add_argument("--period", default=None)
    rem_p = sub.add_parser("remove", help="Remove a company or quarter")
    rem_p.add_argument("--ticker", required=True)
    rem_p.add_argument("--period", default=None)
    rem_p.add_argument(
        "--prune-manifests",
        action="store_true",
        help="Also delete matching inbox/events *.event.json files",
    )
    rem_p.add_argument(
        "--events-dir",
        type=Path,
        default=None,
        help="Events dir for --prune-manifests",
    )
    sync_p = sub.add_parser(
        "sync", help="Match membership to every onboarded company"
    )
    sync_p.add_argument("--dry-run", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    repo_root = (args.repo_root or Path.cwd()).resolve()
    path = (
        Path(args.watchlist)
        if args.watchlist
        else default_watchlist_path(repo_root)
    )
    watchlist = load_watchlist(path)
    if args.action == "list":
        print(json.dumps({"path": str(path), **watchlist.to_document()}, indent=2))
        return 0
    if args.action == "add":
        changed = watchlist.add_entry(args.ticker, args.period)
        save_watchlist_atomic(path, watchlist)
        print(
            json.dumps(
                {
                    "changed": changed,
                    "path": str(path),
                    **watchlist.to_document(),
                },
                indent=2,
            )
        )
        return 0
    if args.action == "sync":
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
    if args.action == "remove":
        changed = watchlist.remove_entry(args.ticker, args.period)
        save_watchlist_atomic(path, watchlist)
        pruned: list[str] = []
        if args.prune_manifests:
            if args.events_dir is None:
                print(
                    "error: --events-dir is required with --prune-manifests",
                    file=sys.stderr,
                )
                return 2
            pruned = prune_event_manifests(
                args.events_dir,
                ticker=args.ticker,
                period=args.period,
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


if __name__ == "__main__":
    raise SystemExit(main())
