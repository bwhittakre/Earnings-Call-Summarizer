#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scripted Quartr historical transcript importer (primary Onboard pull path).

Pulls earnings-call transcripts for a company over a date window and writes
files in the layouts ``LocalFileProvider`` accepts:

* ``transcripts_raw/{TICKER}_FY{yyyy}-Q{n}.txt``  (flat, default)
* ``transcripts_raw/{TICKER}/FY{yyyy}-Q{n}.txt``  (per-ticker directory)

Auth / config
-------------
    export QUARTR_API_KEY=...          # required (header: x-api-key)
    export QUARTR_API_BASE=https://api.quartr.com   # optional

Examples
--------
    python "Structured Narrative/quartr_history_import.py" \\
        --ticker AMZN --years 10 --layout flat

    python "Structured Narrative/quartr_history_import.py" \\
        --ticker TXN --start 2016-01-01 --end 2026-08-01 --layout nested --dry-run

See ``Structured Narrative/README_quartr_history_import.md`` for details.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
DEFAULT_OUT = HERE / "transcripts_raw"
DEFAULT_BASE = os.environ.get("QUARTR_API_BASE", "https://api.quartr.com").rstrip("/")


def _load_quartr_env() -> None:
    """Load QUARTR_* from Structured Narrative /.env and repo-root .env if present."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover
        return
    load_dotenv(HERE / ".env")
    load_dotenv(HERE.parent / ".env")

_PERIOD_RE = re.compile(r"^FY(\d{4})-Q([1-4])$", re.IGNORECASE)
_Q_ONLY_RE = re.compile(r"^Q([1-4])$", re.IGNORECASE)
HttpGet = Callable[[str, Mapping[str, Any] | None], Mapping[str, Any]]


class QuartrImportError(RuntimeError):
    """Raised when the Quartr importer cannot complete a required step."""


@dataclass(frozen=True)
class WrittenTranscript:
    ticker: str
    fiscal_period: str
    path: Path
    event_id: str | int | None = None
    document_id: str | int | None = None
    skipped: bool = False
    reason: str = ""


@dataclass
class ImportResult:
    ticker: str
    company_id: int | None
    written: list[WrittenTranscript] = field(default_factory=list)
    events_seen: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def periods(self) -> list[str]:
        return sorted(
            {item.fiscal_period for item in self.written if not item.skipped},
            key=_period_sort_key,
        )


def _period_sort_key(period: str) -> tuple[int, int, str]:
    match = _PERIOD_RE.match(str(period))
    if not match:
        return (9999, 9, str(period))
    return (int(match.group(1)), int(match.group(2)), str(period))


def normalize_fiscal_period(
    *,
    fiscal_year: Any = None,
    fiscal_period: Any = None,
    title: str = "",
) -> str | None:
    """Normalize Quartr fiscal fields to ``FYyyyy-Qn``."""
    if fiscal_period is not None:
        text = str(fiscal_period).strip().upper()
        if _PERIOD_RE.match(text):
            match = _PERIOD_RE.match(text)
            assert match is not None
            return f"FY{match.group(1)}-Q{match.group(2)}"
        q_only = _Q_ONLY_RE.match(text.removeprefix("FY").strip())
        if q_only and fiscal_year:
            return f"FY{int(fiscal_year)}-Q{q_only.group(1)}"
        if text.startswith("Q") and fiscal_year:
            q_only = _Q_ONLY_RE.match(text)
            if q_only:
                return f"FY{int(fiscal_year)}-Q{q_only.group(1)}"
    if fiscal_year and fiscal_period:
        q = str(fiscal_period).upper().removeprefix("Q")
        if q in {"1", "2", "3", "4"}:
            return f"FY{int(fiscal_year)}-Q{q}"
    match = re.search(r"\bQ([1-4])\b", title or "", re.IGNORECASE)
    year_match = re.search(r"\b(20\d{2})\b", title or "")
    if match and (fiscal_year or year_match):
        year = int(fiscal_year or year_match.group(1))
        return f"FY{year}-Q{match.group(1)}"
    return None


def format_transcript_path(
    out_dir: str | Path,
    ticker: str,
    fiscal_period: str,
    *,
    layout: str = "flat",
) -> Path:
    """Return the destination path for a transcript.

    ``layout``:
      * ``flat``   → ``{out_dir}/{TICKER}_{FY…}.txt``
      * ``nested`` → ``{out_dir}/{TICKER}/{FY…}.txt``
    """
    root = Path(out_dir)
    ticker_key = ticker.strip().upper()
    period = str(fiscal_period).strip().upper()
    if not _PERIOD_RE.match(period):
        raise ValueError(f"fiscal_period must look like FY2024-Q1, got {fiscal_period!r}")
    layout_key = layout.strip().lower()
    if layout_key == "flat":
        return root / f"{ticker_key}_{period}.txt"
    if layout_key == "nested":
        return root / ticker_key / f"{period}.txt"
    raise ValueError(f"Unknown layout {layout!r}; use 'flat' or 'nested'")


def lookback_window(
    years: int,
    *,
    end: datetime | None = None,
) -> tuple[datetime, datetime]:
    end_at = end or datetime.now(timezone.utc)
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=timezone.utc)
    start_at = end_at - timedelta(days=int(years) * 365 + 2)
    return start_at.astimezone(timezone.utc), end_at.astimezone(timezone.utc)


def _default_http_get(url: str, headers: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    request = Request(url, headers={str(k): str(v) for k, v in (headers or {}).items()})
    try:
        with urlopen(request, timeout=60) as response:  # noqa: S310 - operator-configured API
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise QuartrImportError(f"HTTP {exc.code} for {url}: {body[:400]}") from exc
    except URLError as exc:
        raise QuartrImportError(f"Network error for {url}: {exc}") from exc
    data = json.loads(payload) if payload else {}
    if not isinstance(data, Mapping):
        raise QuartrImportError(f"Unexpected JSON payload from {url}")
    return data


class QuartrApiClient:
    """Minimal Quartr Public API v3 client (companies / events / transcripts)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE,
        http_get: HttpGet | None = None,
        pause_seconds: float = 0.15,
    ) -> None:
        if not api_key:
            _load_quartr_env()
        self.api_key = (api_key or os.environ.get("QUARTR_API_KEY") or "").strip()
        self.base_url = (base_url or DEFAULT_BASE).rstrip("/")
        if not api_key:
            env_base = os.environ.get("QUARTR_API_BASE", "").strip()
            if env_base:
                self.base_url = env_base.rstrip("/")
        self.http_get = http_get or _default_http_get
        self.pause_seconds = pause_seconds

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise QuartrImportError(
                "QUARTR_API_KEY is not set. Export it or pass api_key= to QuartrApiClient."
            )
        return {"x-api-key": self.api_key, "Accept": "application/json"}

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        query = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        if self.pause_seconds:
            time.sleep(self.pause_seconds)
        return self.http_get(url, self._headers())

    def resolve_company_id(self, ticker: str) -> int:
        ticker_key = ticker.strip().upper()
        payload = self.get(
            "/public/v3/companies",
            {"tickers": ticker_key, "limit": 20},
        )
        rows = payload.get("data") if isinstance(payload.get("data"), list) else []
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            candidate = str(row.get("ticker") or row.get("symbol") or "").upper()
            if candidate == ticker_key and row.get("id") is not None:
                return int(row["id"])
        if len(rows) == 1 and isinstance(rows[0], Mapping) and rows[0].get("id") is not None:
            return int(rows[0]["id"])
        raise QuartrImportError(f"Could not resolve Quartr companyId for ticker {ticker_key}")

    def iter_events(
        self,
        *,
        company_id: int,
        start: datetime,
        end: datetime,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        cursor: int | None = 0
        while cursor is not None:
            payload = self.get(
                "/public/v3/events",
                {
                    "companyIds": str(company_id),
                    "startDate": start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "endDate": end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "limit": limit,
                    "cursor": cursor,
                    "sortBy": "date",
                    "direction": "asc",
                },
            )
            batch = payload.get("data") if isinstance(payload.get("data"), list) else []
            for row in batch:
                if isinstance(row, Mapping):
                    rows.append(dict(row))
            pagination = payload.get("pagination") if isinstance(payload.get("pagination"), Mapping) else {}
            next_cursor = pagination.get("nextCursor")
            cursor = int(next_cursor) if next_cursor is not None else None
            if not batch:
                break
        return rows

    def list_transcripts_for_event(self, event_id: int | str) -> list[dict[str, Any]]:
        payload = self.get(
            "/public/v3/documents/transcripts",
            {"eventIds": str(event_id), "limit": 20},
        )
        rows = payload.get("data") if isinstance(payload.get("data"), list) else []
        return [dict(row) for row in rows if isinstance(row, Mapping)]

    def fetch_transcript_text(self, document_id: int | str) -> str:
        payload = self.get(f"/public/v3/documents/transcripts/{document_id}")
        return extract_transcript_text(payload)


def extract_transcript_text(payload: Mapping[str, Any]) -> str:
    """Best-effort extraction across Quartr transcript document shapes."""
    for key in ("text", "content", "body", "transcript"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, Mapping):
            nested = extract_transcript_text(value)
            if nested:
                return nested
    paragraphs = payload.get("paragraphs") or payload.get("data")
    if isinstance(paragraphs, list):
        chunks: list[str] = []
        for item in paragraphs:
            if isinstance(item, str) and item.strip():
                chunks.append(item.strip())
            elif isinstance(item, Mapping):
                text = item.get("text") or item.get("content") or item.get("body")
                if isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        if chunks:
            return "\n".join(chunks)
    return ""


def discover_local_transcript_periods(
    out_dir: str | Path,
    ticker: str,
) -> list[str]:
    """Scan flat + nested LocalFileProvider layouts for a ticker."""
    root = Path(out_dir)
    ticker_key = ticker.strip().upper()
    periods: set[str] = set()
    for path in root.glob(f"{ticker_key}_FY*-*-Q*.txt"):
        stem = path.stem
        prefix = f"{ticker_key}_"
        if stem.upper().startswith(prefix):
            periods.add(stem[len(prefix) :].upper())
    nested = root / ticker_key
    if nested.is_dir():
        for path in nested.glob("FY*-*-Q*.txt"):
            periods.add(path.stem.upper())
    return sorted(periods, key=_period_sort_key)


def import_company_history(
    ticker: str,
    *,
    start: datetime,
    end: datetime,
    out_dir: str | Path = DEFAULT_OUT,
    layout: str = "flat",
    client: QuartrApiClient | None = None,
    force: bool = False,
    dry_run: bool = False,
    company_id: int | None = None,
    latest_only: bool = False,
) -> ImportResult:
    """Company → events in window → write transcripts_raw files.

    When *latest_only* is True, stop after the first successfully handled
    (newest) event — used by micro-onboard.
    """
    ticker_key = ticker.strip().upper()
    api = client or QuartrApiClient()
    resolved_id = company_id if company_id is not None else api.resolve_company_id(ticker_key)
    result = ImportResult(ticker=ticker_key, company_id=resolved_id)
    events = api.iter_events(company_id=resolved_id, start=start, end=end)
    # Newest first so latest_only grabs the most recent call.
    def _event_sort_key(event: dict) -> str:
        for key in ("reportDate", "date", "eventDate", "callDate", "updatedAt"):
            value = event.get(key)
            if value:
                return str(value)
        return ""

    events = sorted(events, key=_event_sort_key, reverse=True)
    result.events_seen = len(events)

    for event in events:
        event_id = event.get("id")
        period = normalize_fiscal_period(
            fiscal_year=event.get("fiscalYear"),
            fiscal_period=event.get("fiscalPeriod") or event.get("fiscal_period"),
            title=str(event.get("title") or ""),
        )
        if not period:
            result.errors.append(f"skip event {event_id}: could not parse fiscal period")
            continue
        if event_id is None:
            result.errors.append(f"skip {period}: missing event id")
            continue
        try:
            docs = api.list_transcripts_for_event(event_id)
        except QuartrImportError as exc:
            result.errors.append(f"{period} event {event_id}: {exc}")
            continue
        if not docs:
            result.written.append(
                WrittenTranscript(
                    ticker=ticker_key,
                    fiscal_period=period,
                    path=format_transcript_path(out_dir, ticker_key, period, layout=layout),
                    event_id=event_id,
                    skipped=True,
                    reason="no transcript document",
                )
            )
            continue
        doc = docs[0]
        document_id = doc.get("id")
        dest = format_transcript_path(out_dir, ticker_key, period, layout=layout)
        if dest.exists() and not force:
            result.written.append(
                WrittenTranscript(
                    ticker=ticker_key,
                    fiscal_period=period,
                    path=dest,
                    event_id=event_id,
                    document_id=document_id,
                    skipped=True,
                    reason="exists",
                )
            )
            if latest_only:
                break
            continue
        if dry_run:
            result.written.append(
                WrittenTranscript(
                    ticker=ticker_key,
                    fiscal_period=period,
                    path=dest,
                    event_id=event_id,
                    document_id=document_id,
                    skipped=True,
                    reason="dry_run",
                )
            )
            if latest_only:
                break
            continue
        if document_id is None:
            result.errors.append(f"{period}: transcript missing document id")
            continue
        try:
            text = api.fetch_transcript_text(document_id)
        except QuartrImportError as exc:
            result.errors.append(f"{period} document {document_id}: {exc}")
            continue
        if not text.strip():
            result.errors.append(f"{period}: empty transcript body")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text.strip() + "\n", encoding="utf-8")
        result.written.append(
            WrittenTranscript(
                ticker=ticker_key,
                fiscal_period=period,
                path=dest,
                event_id=event_id,
                document_id=document_id,
            )
        )
        if latest_only:
            break
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--years", type=int, default=None, help="Lookback years from --end / now")
    parser.add_argument("--start", help="ISO start date/datetime (UTC)")
    parser.add_argument("--end", help="ISO end date/datetime (UTC)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument(
        "--layout",
        choices=("flat", "nested"),
        default="flat",
        help="LocalFileProvider path layout (default: flat)",
    )
    parser.add_argument("--company-id", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)

    end = (
        datetime.fromisoformat(args.end.replace("Z", "+00:00"))
        if args.end
        else datetime.now(timezone.utc)
    )
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if args.start:
        start = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    elif args.years:
        start, end = lookback_window(args.years, end=end)
    else:
        start, end = lookback_window(10, end=end)

    try:
        result = import_company_history(
            args.ticker,
            start=start,
            end=end,
            out_dir=args.out,
            layout=args.layout,
            company_id=args.company_id,
            force=args.force,
            dry_run=args.dry_run,
        )
    except QuartrImportError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    payload = {
        "ticker": result.ticker,
        "company_id": result.company_id,
        "events_seen": result.events_seen,
        "periods": result.periods,
        "written": [
            {
                "fiscal_period": item.fiscal_period,
                "path": str(item.path),
                "skipped": item.skipped,
                "reason": item.reason,
                "event_id": item.event_id,
                "document_id": item.document_id,
            }
            for item in result.written
        ],
        "errors": result.errors,
        "start": start.isoformat(),
        "end": end.isoformat(),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"{result.ticker}: company_id={result.company_id} "
            f"events={result.events_seen} periods={len(result.periods)}"
        )
        for item in result.written:
            flag = "=" if item.skipped else "+"
            extra = f" ({item.reason})" if item.reason else ""
            print(f"  {flag} {item.path.name}{extra}")
        for err in result.errors:
            print(f"  ! {err}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
