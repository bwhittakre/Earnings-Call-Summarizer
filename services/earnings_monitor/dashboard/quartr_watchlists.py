"""Sync Quartr watchlists into config/sectors for Roz Sector filter."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.ingest.company_lists import DEFAULT_SECTORS_DIR

LOG = logging.getLogger(__name__)

META_NAME = ".quartr_watchlists_meta.json"
DEFAULT_TTL_SECONDS = 3600
_SLUG_RE = re.compile(r"[^a-z0-9]+")


@dataclass
class WatchlistSyncResult:
    synced_at: str
    watchlists: int = 0
    files_written: list[str] = field(default_factory=list)
    tickers: list[str] = field(default_factory=list)
    micro_onboarded: list[str] = field(default_factory=list)
    already_present: list[str] = field(default_factory=list)
    pending_transcript: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    skipped_unmapped: list[str] = field(default_factory=list)
    error: str | None = None
    from_cache: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _http_get_json(url: str, headers: Mapping[str, str]) -> Mapping[str, Any]:
    req = Request(url, headers=dict(headers), method="GET")
    with urlopen(req, timeout=45) as resp:  # noqa: S310 — operator-configured API
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise RuntimeError(f"Unexpected Quartr payload type: {type(payload)}")
    return payload


def slugify_watchlist_name(name: str, watchlist_id: Any) -> str:
    base = _SLUG_RE.sub("_", str(name or "").strip().lower()).strip("_")
    if not base:
        base = f"list_{watchlist_id}"
    return f"quartr_{base}"[:80]


def meta_path(sectors_dir: Path | None = None) -> Path:
    return (sectors_dir or DEFAULT_SECTORS_DIR) / META_NAME


def load_sync_meta(sectors_dir: Path | None = None) -> dict[str, Any]:
    path = meta_path(sectors_dir)
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def sync_is_fresh(
    sectors_dir: Path | None = None,
    *,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    now: datetime | None = None,
) -> bool:
    meta = load_sync_meta(sectors_dir)
    raw = meta.get("synced_at")
    if not raw:
        return False
    try:
        stamped = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if stamped.tzinfo is None:
        stamped = stamped.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    return (current - stamped.astimezone(timezone.utc)).total_seconds() < ttl_seconds


def write_watchlist_sector_file(
    sectors_dir: Path,
    *,
    stem: str,
    tickers: Sequence[str],
    watchlist_id: Any,
    watchlist_name: str,
    synced_at: str,
) -> Path:
    path = sectors_dir / f"{stem}.txt"
    lines = [
        f"# Quartr watchlist: {watchlist_name} (id={watchlist_id})",
        f"# synced_at: {synced_at}",
    ]
    for ticker in tickers:
        key = str(ticker).strip().upper()
        if key:
            lines.append(key)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class QuartrWatchlistClient:
    """Minimal Public API client for watchlists (+ company ticker resolve)."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        http_get: Callable[[str, Mapping[str, str]], Mapping[str, Any]] | None = None,
    ) -> None:
        self.api_key = (api_key or os.environ.get("QUARTR_API_KEY") or "").strip()
        self.base_url = (
            base_url or os.environ.get("QUARTR_API_BASE") or "https://api.quartr.com"
        ).rstrip("/")
        self._http_get = http_get or _http_get_json
        self._ticker_cache: dict[int, str] = {}

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("QUARTR_API_KEY is not set")
        return {"x-api-key": self.api_key, "Accept": "application/json"}

    def get(self, path: str, params: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        return self._http_get(f"{self.base_url}{path}{query}", self._headers())

    def list_watchlists(self) -> list[dict[str, Any]]:
        for path in ("/public/v3/watchlists", "/public/v1/watchlists"):
            try:
                payload = self.get(path, {"limit": 100})
            except HTTPError as exc:
                if exc.code in {404, 405}:
                    continue
                raise
            rows = payload.get("data") if isinstance(payload.get("data"), list) else []
            if rows:
                return [dict(row) for row in rows if isinstance(row, Mapping)]
            # empty but valid endpoint
            if "data" in payload:
                return []
        raise RuntimeError("Quartr watchlists endpoint not available for this API key")

    def get_watchlist(self, watchlist_id: int | str) -> dict[str, Any]:
        for path in (
            f"/public/v3/watchlists/{watchlist_id}",
            f"/public/v1/watchlists/{watchlist_id}",
        ):
            try:
                payload = self.get(path)
            except HTTPError as exc:
                if exc.code in {404, 405}:
                    continue
                raise
            if isinstance(payload.get("data"), Mapping):
                return dict(payload["data"])
            if isinstance(payload, Mapping) and payload.get("id") is not None:
                return dict(payload)
        raise RuntimeError(f"Watchlist {watchlist_id} not found")

    def resolve_ticker(self, company_id: int) -> str | None:
        if company_id in self._ticker_cache:
            return self._ticker_cache[company_id]
        try:
            payload = self.get(f"/public/v3/companies/{company_id}")
        except (HTTPError, URLError, TimeoutError, RuntimeError):
            return None
        data = payload.get("data") if isinstance(payload.get("data"), Mapping) else payload
        if not isinstance(data, Mapping):
            return None
        for key in ("ticker", "symbol", "primaryTicker"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                ticker = value.strip().upper()
                self._ticker_cache[company_id] = ticker
                return ticker
        tickers = data.get("tickers")
        if isinstance(tickers, list) and tickers:
            first = tickers[0]
            if isinstance(first, str) and first.strip():
                ticker = first.strip().upper()
                self._ticker_cache[company_id] = ticker
                return ticker
            if isinstance(first, Mapping):
                value = first.get("ticker") or first.get("symbol")
                if isinstance(value, str) and value.strip():
                    ticker = value.strip().upper()
                    self._ticker_cache[company_id] = ticker
                    return ticker
        return None


def extract_watchlist_companies(watchlist: Mapping[str, Any]) -> list[dict[str, Any]]:
    for key in ("companies", "members", "items", "data"):
        rows = watchlist.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, Mapping)]
    return []


def company_to_ticker(
    row: Mapping[str, Any],
    *,
    client: QuartrWatchlistClient,
) -> str | None:
    for key in ("ticker", "symbol", "primaryTicker"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    company = row.get("company")
    if isinstance(company, Mapping):
        nested = company_to_ticker(company, client=client)
        if nested:
            return nested
        company_id = company.get("id") or company.get("companyId")
    else:
        company_id = row.get("companyId") or row.get("id")
    if company_id is None:
        return None
    try:
        return client.resolve_ticker(int(company_id))
    except (TypeError, ValueError):
        return None


def sync_quartr_watchlists(
    *,
    sectors_dir: Path | None = None,
    repo_root: Path | None = None,
    available_tickers: Sequence[str] | None = None,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    force: bool = False,
    micro_onboard: bool = True,
    max_micro_onboards: int = 5,
    client: QuartrWatchlistClient | None = None,
    onboard_fn: Callable[..., Any] | None = None,
    state=None,
    configured_tickers: Sequence[str] = (),
    now: datetime | None = None,
) -> WatchlistSyncResult:
    """Fetch Quartr watchlists, write sector files, micro-onboard missing names."""
    directory = Path(sectors_dir or DEFAULT_SECTORS_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    current = now or datetime.now(timezone.utc)
    synced_at = current.astimezone(timezone.utc).isoformat()
    result = WatchlistSyncResult(synced_at=synced_at)

    if not force and sync_is_fresh(directory, ttl_seconds=ttl_seconds, now=current):
        meta = load_sync_meta(directory)
        result.from_cache = True
        result.watchlists = int(meta.get("watchlists") or 0)
        result.files_written = list(meta.get("files") or [])
        result.tickers = list(meta.get("tickers") or [])
        return result

    try:
        api = client or QuartrWatchlistClient()
        if not api.api_key:
            # Soft no-op when the operator has not configured Quartr.
            LOG.info("Quartr watchlist sync skipped: QUARTR_API_KEY is not set")
            return result
        watchlists = api.list_watchlists()
    except Exception as exc:  # noqa: BLE001
        result.error = str(exc)
        LOG.warning("Quartr watchlist sync failed: %s", exc)
        return result

    available = {
        str(t).strip().upper() for t in (available_tickers or ()) if str(t).strip()
    }
    all_tickers: list[str] = []
    missing: list[str] = []

    for entry in watchlists:
        watchlist_id = entry.get("id")
        name = str(entry.get("name") or entry.get("title") or watchlist_id)
        try:
            detail = api.get_watchlist(watchlist_id) if watchlist_id is not None else entry
        except Exception as exc:  # noqa: BLE001
            LOG.warning("Failed to load watchlist %s: %s", watchlist_id, exc)
            detail = entry
        companies = extract_watchlist_companies(detail) or extract_watchlist_companies(entry)
        tickers: list[str] = []
        for company in companies:
            ticker = company_to_ticker(company, client=api)
            if not ticker:
                cid = company.get("companyId") or company.get("id")
                result.skipped_unmapped.append(str(cid))
                continue
            if ticker not in tickers:
                tickers.append(ticker)
            if ticker not in all_tickers:
                all_tickers.append(ticker)
            if available and ticker not in available:
                missing.append(ticker)
            elif not available:
                # No dataset yet — treat all as candidates for micro-onboard.
                missing.append(ticker)

        stem = slugify_watchlist_name(name, watchlist_id)
        path = write_watchlist_sector_file(
            directory,
            stem=stem,
            tickers=tickers,
            watchlist_id=watchlist_id,
            watchlist_name=name,
            synced_at=synced_at,
        )
        result.files_written.append(path.name)

    result.watchlists = len(watchlists)
    result.tickers = all_tickers
    # Deduplicate missing while preserving order.
    missing = list(dict.fromkeys(missing))

    if micro_onboard and missing and repo_root is not None:
        from services.earnings_monitor.latest_onboard import run_latest_call_onboard

        runner = onboard_fn or run_latest_call_onboard
        for ticker in missing[: max(0, int(max_micro_onboards))]:
            try:
                onboarded = runner(
                    repo_root=Path(repo_root),
                    ticker=ticker,
                    state=state,
                    configured_tickers=configured_tickers or all_tickers,
                )
                status = getattr(onboarded, "status", None) or (
                    onboarded.get("status") if isinstance(onboarded, dict) else "failed"
                )
                if status in {"latest_call_onboarded"}:
                    result.micro_onboarded.append(ticker)
                elif status in {"already_present"}:
                    result.already_present.append(ticker)
                elif status in {"pending_transcript"}:
                    result.pending_transcript.append(ticker)
                else:
                    result.failed.append(ticker)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("Micro-onboard failed for %s: %s", ticker, exc)
                result.failed.append(ticker)
            time.sleep(0.2)

    meta = {
        "synced_at": synced_at,
        "watchlists": result.watchlists,
        "files": result.files_written,
        "tickers": result.tickers,
        "micro_onboarded": result.micro_onboarded,
        "pending_transcript": result.pending_transcript,
        "failed": result.failed,
    }
    meta_path(directory).write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result
