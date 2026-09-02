"""Host calendar publisher: Quartr event dumps → watched ``*.event.json``.

Run on the host (Cursor Automation / MCP), not inside Docker. Writes atomic
manifests for onboarded overlay tickers so ``EARNINGS_MONITOR_PROVIDER=watched``
can auto-arm without a manual ``arm`` each quarter.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from .automation_watchlist import (
    Watchlist,
    default_watchlist_path,
    load_watchlist,
)
from .eligibility import (
    default_overlay_dir,
    list_overlay_tickers,
    registry_tickers,
)
from .providers import (
    EVENT_MANIFEST_SUFFIX,
    _content_date,
    _first_value,
    _fiscal_period,
    _parse_datetime,
    write_event_manifest_atomic,
)
from .ticker_book import load_sector_tickers, sector_tickers_path

LOG = logging.getLogger(__name__)

_EARNINGS_PARENT = frozenset({"earnings_call", "earnings"})
_QUARTER_TYPES = frozenset({"q_1", "q_2", "q_3", "q_4", "q1", "q2", "q3", "q4"})
_PERIOD_RE = re.compile(r"^FY\d{4}-Q[1-4]$", re.IGNORECASE)


class EventListGateway(Protocol):
    """Injectable Quartr ``list_events`` boundary for tests / automation."""

    def list_events(self, *, ticker: str) -> Sequence[Mapping[str, Any]]: ...


class JsonEventsDumpGateway:
    """Load a saved Quartr ``list_events`` (or multi-ticker) JSON dump."""

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self._by_ticker = _index_events_dump(self.path)

    def list_events(self, *, ticker: str) -> Sequence[Mapping[str, Any]]:
        return self._by_ticker.get(ticker.strip().upper(), ())


class CallableEventGateway:
    def __init__(self, fetch: Callable[[str], Sequence[Mapping[str, Any]]]):
        self._fetch = fetch

    def list_events(self, *, ticker: str) -> Sequence[Mapping[str, Any]]:
        rows = self._fetch(ticker.strip().upper())
        return list(rows)


class MergedJsonDirGateway:
    """Merge all ``*.json`` Quartr dumps in a directory (per-ticker files)."""

    def __init__(self, directory: Path | str):
        self.directory = Path(directory)
        self._by_ticker: dict[str, list[Mapping[str, Any]]] = {}
        if not self.directory.is_dir():
            raise ValueError(f"calendar dump directory not found: {self.directory}")
        for path in sorted(self.directory.glob("*.json")):
            try:
                chunk = _index_events_dump(path)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                LOG.warning("Ignoring bad calendar dump %s: %s", path, exc)
                continue
            for ticker, rows in chunk.items():
                bucket = self._by_ticker.setdefault(ticker, [])
                bucket.extend(rows)

    def list_events(self, *, ticker: str) -> Sequence[Mapping[str, Any]]:
        return self._by_ticker.get(ticker.strip().upper(), ())


def _index_events_dump(path: Path) -> dict[str, list[Mapping[str, Any]]]:
    # PowerShell Set-Content often writes a UTF-8 BOM.
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    rows: list[Any]
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        if isinstance(payload.get("events"), list):
            rows = list(payload["events"])
        elif isinstance(payload.get("data"), list):
            rows = list(payload["data"])
        elif payload.get("id") is not None or payload.get("eventType") is not None:
            # Single Quartr event object.
            rows = [payload]
        else:
            # Single-ticker dump keyed by ticker → list
            rows = []
            for key, value in payload.items():
                if isinstance(value, list) and key.strip().upper() == key.upper():
                    for item in value:
                        if isinstance(item, Mapping):
                            enriched = dict(item)
                            enriched.setdefault("ticker", key.upper())
                            rows.append(enriched)
            if not rows:
                raise ValueError(
                    f"unrecognized events dump shape in {path}: expected list, "
                    "single event, {events|data: [...]}, or {TICKER: [...]}"
                )
    else:
        raise ValueError(f"events dump must be a JSON object or array: {path}")

    by_ticker: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        company = row.get("company")
        ticker = str(
            row.get("ticker")
            or row.get("symbol")
            or _first_value(company, "ticker", "symbol")
            or ""
        ).strip().upper()
        if not ticker:
            continue
        by_ticker.setdefault(ticker, []).append(row)
    return by_ticker


def _is_earnings_event(row: Mapping[str, Any]) -> bool:
    parent = str(row.get("parentEventType") or row.get("parent_event_type") or "").lower()
    event_type = str(row.get("eventType") or row.get("event_type") or "").lower()
    if parent in _EARNINGS_PARENT:
        return True
    if event_type in _QUARTER_TYPES:
        return True
    title = str(row.get("title") or "").lower()
    return "earnings" in title and bool(re.search(r"\bq[1-4]\b", title))


def _event_source_url(row: Mapping[str, Any], event_id: str) -> str | None:
    for key in ("url", "source_url", "sourceUrl", "webUrl"):
        value = row.get(key)
        if isinstance(value, str) and value.strip().startswith(("http://", "https://")):
            return value.strip()
    company = row.get("company")
    company_id = row.get("companyId") or row.get("company_id")
    if company_id is None and isinstance(company, Mapping):
        company_id = company.get("id") or company.get("companyId")
    if company_id is not None:
        return (
            f"https://web.quartr.com/companies/{company_id}/events/{event_id}/overview"
        )
    return None


def quartr_row_to_manifest(
    row: Mapping[str, Any],
    *,
    ticker: str | None = None,
) -> dict[str, Any] | None:
    """Map one Quartr event row to a v1 watched event manifest, or None if skip."""
    if not _is_earnings_event(row):
        return None
    company = row.get("company")
    resolved_ticker = (
        ticker
        or str(
            row.get("ticker")
            or row.get("symbol")
            or _first_value(company, "ticker", "symbol")
            or ""
        )
    ).strip().upper()
    if not resolved_ticker:
        return None
    event_id = str(row.get("event_id") or row.get("id") or "").strip()
    period = _fiscal_period(row)
    if not event_id or not period or not _PERIOD_RE.fullmatch(period):
        return None
    generic = row.get("scheduled_at") or row.get("date") or row.get("startDate")
    report_raw = _content_date(row, "report") or row.get("report_at") or generic
    call_raw = (
        _content_date(row, "call")
        or row.get("call_at")
        or generic
        or report_raw
    )
    if not report_raw or not call_raw:
        return None
    source_url = _event_source_url(row, event_id)
    if not source_url:
        return None
    report_at = _parse_datetime(report_raw)
    call_at = _parse_datetime(call_raw)
    if report_at > call_at:
        # Quartr estimates the report and call timestamps independently, so for
        # a quarter that is still months out they drift apart and the report can
        # land days AFTER the call (GILD: call Oct 29, report Nov 6). Roz's model
        # requires call_at >= report_at, and results are necessarily public by
        # the time the call starts, so the call time is the latest defensible
        # release time. The real values arrive via T-7 re-verification.
        LOG.info(
            "%s %s: Quartr report_at %s is after call_at %s (estimated dates); "
            "clamping report_at to the call",
            resolved_ticker,
            period,
            report_at.isoformat(),
            call_at.isoformat(),
        )
        report_at = call_at
    title = str(row.get("title") or f"{resolved_ticker} {period} earnings call").strip()
    return {
        "schema_version": 1,
        "provider_event_id": event_id,
        "ticker": resolved_ticker,
        "fiscal_period": period.upper(),
        "report_at": report_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "call_at": call_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "title": title,
        "source_url": source_url,
    }


@dataclass(frozen=True)
class PublishResult:
    ticker: str
    provider_event_id: str
    fiscal_period: str
    path: str
    skipped_reason: str | None = None
    #: Set only when this sweep MOVED an already-published call. Re-verifying a
    #: date is worthless if the answer is invisible, so a change is reported
    #: rather than silently overwritten.
    call_at: str | None = None
    previous_call_at: str | None = None

    @property
    def rescheduled(self) -> bool:
        return bool(
            self.previous_call_at
            and self.call_at
            and self.previous_call_at != self.call_at
        )


@dataclass(frozen=True)
class DueSweepTarget:
    """Near-call work item for MCP dump + live_print_loop / quartr_sweep."""

    event_id: str
    ticker: str
    fiscal_period: str
    call_at: str
    source_url: str | None = None
    is_live_hint: bool = False


def published_call_at(path: Path) -> str | None:
    """The call time already on disk for this quarter, if any.

    Read before overwriting so a moved date can be reported. An unreadable or
    malformed manifest reads as "nothing published" -- this is reporting, and it
    must never be the reason a sweep fails.
    """
    try:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    value = payload.get("call_at")
    return str(value) if value else None


def manifest_path_for(events_dir: Path, ticker: str, fiscal_period: str) -> Path:
    return (
        Path(events_dir)
        / f"{ticker.strip().upper()}-{fiscal_period.strip().upper()}{EVENT_MANIFEST_SUFFIX}"
    )


def resolve_publish_tickers(
    *,
    tickers: Sequence[str] | None,
    repo_root: Path,
    overlay_dir: Path,
    sector: str | None = None,
    watchlist: Watchlist | None = None,
) -> tuple[str, ...]:
    # Onboarded = overlays plus the in-code registry, matching discovery
    # eligibility. Gating publish on overlays alone would drop the original tech
    # book, which predates overlay files and has none -- so their manifests
    # would never be written even when watchlisted.
    onboarded = list_overlay_tickers(overlay_dir) | registry_tickers(repo_root)
    if tickers:
        requested = [t.strip().upper() for t in tickers if t.strip()]
        return tuple(t for t in dict.fromkeys(requested) if t in onboarded)
    # Explicit watchlist mode: empty entries = automate nothing.
    if watchlist is not None:
        return tuple(t for t in watchlist.iter_tickers() if t in onboarded)
    # --no-watchlist fallback: onboarded ∩ sector book (if present), else all.
    if sector:
        book = set(load_sector_tickers(sector_tickers_path(repo_root, sector)))
        if book:
            return tuple(sorted(onboarded & book))
    return tuple(sorted(onboarded))


def dedupe_by_period(
    manifests: Iterable[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """One manifest per (ticker, fiscal_period), earliest call time wins.

    Quartr can list several events for one quarter -- MU's FY2026-Q4 comes back
    as both the call at 20:30Z and a "Q4 2026 Post" follow-on at 22:00Z. Both
    map to the same manifest filename and the same unique (ticker,
    fiscal_period) row in the monitor, so without a rule the winner is whichever
    happened to be written last, and Roz could end up armed against the
    post-earnings session instead of the call.

    Earliest wins because the results call always precedes the sessions that
    discuss it, and it is a property of the schedule rather than of Quartr's
    title wording.
    """
    best: dict[tuple[str, str], dict[str, Any]] = {}
    for manifest in manifests:
        key = (str(manifest["ticker"]), str(manifest["fiscal_period"]))
        current = best.get(key)
        if current is None:
            best[key] = dict(manifest)
            continue
        if _parse_datetime(manifest["call_at"]) < _parse_datetime(current["call_at"]):
            LOG.info(
                "%s %s: preferring event %s over %s (earlier call time)",
                key[0],
                key[1],
                manifest["provider_event_id"],
                current["provider_event_id"],
            )
            best[key] = dict(manifest)
    return list(best.values())


def publish_calendar(
    gateway: EventListGateway,
    *,
    tickers: Sequence[str],
    events_dir: Path,
    horizon_days: int = 30,
    now: datetime | None = None,
    dry_run: bool = False,
    watchlist: Watchlist | None = None,
) -> list[PublishResult]:
    """Write watched manifests for upcoming earnings within the horizon."""
    if horizon_days < 0:
        raise ValueError("horizon_days must be >= 0")
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    else:
        clock = clock.astimezone(timezone.utc)
    until = clock + timedelta(days=horizon_days)
    events_dir = Path(events_dir)
    results: list[PublishResult] = []

    for ticker in tickers:
        key = ticker.strip().upper()
        try:
            rows = gateway.list_events(ticker=key)
        except Exception as exc:  # noqa: BLE001 — surface per-ticker, continue
            LOG.warning("list_events failed for %s: %s", key, exc)
            results.append(
                PublishResult(
                    ticker=key,
                    provider_event_id="",
                    fiscal_period="",
                    path="",
                    skipped_reason=f"list_events_error:{exc}",
                )
            )
            continue
        for manifest in dedupe_by_period(
            m
            for m in (quartr_row_to_manifest(row, ticker=key) for row in rows)
            if m is not None
        ):
            if watchlist is not None and not watchlist.is_automated(
                manifest["ticker"], manifest["fiscal_period"]
            ):
                results.append(
                    PublishResult(
                        ticker=manifest["ticker"],
                        provider_event_id=manifest["provider_event_id"],
                        fiscal_period=manifest["fiscal_period"],
                        path="",
                        skipped_reason="not_on_watchlist",
                    )
                )
                continue
            call_at = _parse_datetime(manifest["call_at"])
            if call_at < clock or call_at > until:
                continue
            path = manifest_path_for(
                events_dir, manifest["ticker"], manifest["fiscal_period"]
            )
            previous = published_call_at(path)
            if previous and previous != manifest["call_at"]:
                LOG.warning(
                    "SCHEDULE CHANGED %s %s: call_at %s -> %s",
                    manifest["ticker"],
                    manifest["fiscal_period"],
                    previous,
                    manifest["call_at"],
                )
            if dry_run:
                results.append(
                    PublishResult(
                        ticker=manifest["ticker"],
                        provider_event_id=manifest["provider_event_id"],
                        fiscal_period=manifest["fiscal_period"],
                        path=str(path),
                        skipped_reason="dry_run",
                        call_at=manifest["call_at"],
                        previous_call_at=previous,
                    )
                )
                continue
            try:
                wrote = write_event_manifest_atomic(path, manifest)
            except Exception as exc:  # noqa: BLE001 - one row must not end the run
                # A sweep covers the whole book, so aborting on a single
                # malformed row leaves the inbox half-written and the remaining
                # companies unarmed with no obvious sign anything went wrong.
                LOG.warning(
                    "skipping %s %s: %s",
                    manifest["ticker"],
                    manifest["fiscal_period"],
                    exc,
                )
                results.append(
                    PublishResult(
                        ticker=manifest["ticker"],
                        provider_event_id=manifest["provider_event_id"],
                        fiscal_period=manifest["fiscal_period"],
                        path="",
                        skipped_reason=f"invalid_manifest:{exc}",
                    )
                )
                continue
            results.append(
                PublishResult(
                    ticker=manifest["ticker"],
                    provider_event_id=manifest["provider_event_id"],
                    fiscal_period=manifest["fiscal_period"],
                    path=str(wrote),
                    call_at=manifest["call_at"],
                    previous_call_at=previous,
                )
            )
            LOG.info(
                "published %s %s event=%s -> %s",
                manifest["ticker"],
                manifest["fiscal_period"],
                manifest["provider_event_id"],
                wrote,
            )
    return results


def list_due_sweep_targets(
    gateway: EventListGateway,
    *,
    tickers: Sequence[str],
    within_hours: float = 6.0,
    now: datetime | None = None,
    watchlist: Watchlist | None = None,
) -> list[DueSweepTarget]:
    """Events whose call_at is within ``within_hours`` (past or future)."""
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None:
        clock = clock.replace(tzinfo=timezone.utc)
    else:
        clock = clock.astimezone(timezone.utc)
    window = timedelta(hours=within_hours)
    due: list[DueSweepTarget] = []
    for ticker in tickers:
        key = ticker.strip().upper()
        for row in gateway.list_events(ticker=key):
            manifest = quartr_row_to_manifest(row, ticker=key)
            if manifest is None:
                continue
            if watchlist is not None and not watchlist.is_automated(
                manifest["ticker"], manifest["fiscal_period"]
            ):
                continue
            call_at = _parse_datetime(manifest["call_at"])
            if abs(call_at - clock) > window:
                continue
            is_live = bool(row.get("isLive") or row.get("is_live"))
            due.append(
                DueSweepTarget(
                    event_id=manifest["provider_event_id"],
                    ticker=manifest["ticker"],
                    fiscal_period=manifest["fiscal_period"],
                    call_at=manifest["call_at"],
                    source_url=manifest.get("source_url"),
                    is_live_hint=is_live,
                )
            )
    due.sort(key=lambda item: item.call_at)
    return due


def write_due_worklist(path: Path | str, due: Sequence[DueSweepTarget]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "due_sweep": [
            {
                "event_id": item.event_id,
                "ticker": item.ticker,
                "fiscal_period": item.fiscal_period,
                "call_at": item.call_at,
                "source_url": item.source_url,
                "is_live_hint": item.is_live_hint,
            }
            for item in due
        ]
    }
    destination.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return destination


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m services.earnings_monitor.calendar_publish",
        description=(
            "Publish watched *.event.json manifests from Quartr list_events dumps "
            "for onboarded (overlay) tickers."
        ),
    )
    parser.add_argument(
        "--tickers",
        default="",
        help="Comma-separated tickers (default: overlay ∩ sector book)",
    )
    parser.add_argument(
        "--events-dir",
        type=Path,
        required=True,
        help="Directory for atomic *.event.json (Compose inbox/events)",
    )
    parser.add_argument(
        "--from-json",
        type=Path,
        help="Path to Quartr list_events JSON dump (JsonEventsDumpGateway)",
    )
    parser.add_argument(
        "--from-json-dir",
        type=Path,
        help="Directory of Quartr list_events JSON dumps (MergedJsonDirGateway)",
    )
    parser.add_argument(
        "--horizon-days",
        type=int,
        default=30,
        help="Publish events with call_at within this many days (default 30)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repo root for overlay/sector resolution (default: cwd)",
    )
    parser.add_argument(
        "--overlay-dir",
        type=Path,
        default=None,
        help="company_overlays directory (default: <repo>/Structured Narrative/config/company_overlays)",
    )
    parser.add_argument(
        "--sector",
        default="xlk_tech",
        help="Sector book file stem under config/sectors (default xlk_tech)",
    )
    parser.add_argument(
        "--watchlist",
        type=Path,
        default=None,
        help="Automation watchlist YAML (default: config/automation_watchlist.yaml)",
    )
    parser.add_argument(
        "--no-watchlist",
        action="store_true",
        help="Ignore automation watchlist (overlay/sector filter only)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve and print manifests without writing",
    )
    parser.add_argument(
        "--list-due",
        action="store_true",
        help="Also print near-call DueSweepTarget worklist as JSON",
    )
    parser.add_argument(
        "--worklist-out",
        type=Path,
        default=None,
        help="Write due-sweep worklist JSON (implies due listing)",
    )
    parser.add_argument(
        "--due-within-hours",
        type=float,
        default=6.0,
        help="With --list-due/--worklist-out, window around call_at in hours (default 6)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_arg_parser().parse_args(argv)
    if args.from_json is None and args.from_json_dir is None:
        print(
            "error: --from-json or --from-json-dir is required (host MCP list_events dump). "
            "Quartr REST inside Docker is out of scope.",
            file=sys.stderr,
        )
        return 2
    if args.from_json is not None and args.from_json_dir is not None:
        print("error: use only one of --from-json or --from-json-dir", file=sys.stderr)
        return 2
    repo_root = (args.repo_root or Path.cwd()).resolve()
    overlay_dir = Path(args.overlay_dir) if args.overlay_dir else default_overlay_dir(repo_root)
    watchlist: Watchlist | None = None
    if not args.no_watchlist:
        wl_path = args.watchlist or default_watchlist_path(repo_root)
        watchlist = load_watchlist(wl_path)
    tickers_arg = [t for t in args.tickers.split(",") if t.strip()] if args.tickers else None
    tickers = resolve_publish_tickers(
        tickers=tickers_arg,
        repo_root=repo_root,
        overlay_dir=overlay_dir,
        sector=args.sector,
        watchlist=watchlist,
    )
    if not tickers:
        print(
            json.dumps(
                {
                    "published": [],
                    "tickers": [],
                    "warning": "no eligible overlay tickers (check watchlist + overlays)",
                    "overlay_dir": str(overlay_dir),
                },
                indent=2,
            )
        )
        return 0
    gateway: EventListGateway
    if args.from_json_dir is not None:
        gateway = MergedJsonDirGateway(args.from_json_dir)
    else:
        gateway = JsonEventsDumpGateway(args.from_json)
    published = publish_calendar(
        gateway,
        tickers=tickers,
        events_dir=Path(args.events_dir),
        horizon_days=args.horizon_days,
        dry_run=bool(args.dry_run),
        watchlist=watchlist,
    )
    payload: dict[str, Any] = {
        "tickers": list(tickers),
        "published": [item.__dict__ for item in published],
        "events_dir": str(Path(args.events_dir)),
        "dry_run": bool(args.dry_run),
    }
    want_due = bool(args.list_due or args.worklist_out)
    if want_due:
        due = list_due_sweep_targets(
            gateway,
            tickers=tickers,
            within_hours=args.due_within_hours,
            watchlist=watchlist,
        )
        payload["due_sweep"] = [item.__dict__ for item in due]
        if args.worklist_out is not None:
            wrote = write_due_worklist(args.worklist_out, due)
            payload["worklist_out"] = str(wrote)
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
