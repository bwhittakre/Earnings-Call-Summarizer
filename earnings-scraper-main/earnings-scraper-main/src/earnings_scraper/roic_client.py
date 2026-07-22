"""ROIC.ai earnings-call transcript client (primary transcript source).

Docs:  https://www.roic.ai/api/docs/earnings-calls
Auth:  pass the API key as the ``apikey`` query param (config.ROIC_API_KEY).
Free tier: 5 requests/minute, 2 years of history, all public companies.

Three endpoints are wrapped:
    list_calls(identifier)          -> [{symbol, year, quarter, date}, ...]
    latest(identifier)              -> Transcript
    get_transcript(id, year, qtr)   -> Transcript

Errors surface as ``RoicError`` carrying the HTTP status so the caller can
decide whether to fall back to SEC EDGAR (404 = no transcript, 403 = outside
the plan's history window) or abort (401 = bad key).
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from . import config


class RoicError(RuntimeError):
    """A non-200 response (or missing config) from the ROIC.ai API."""

    def __init__(self, message: str, *, status: int | None = None, retry_after: int | None = None):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


@dataclass
class Transcript:
    symbol: str
    year: int
    quarter: int
    date: str
    content: str

    @property
    def has_content(self) -> bool:
        return bool(self.content and self.content.strip())


# Module-level throttle so batch runs across many tickers still respect the
# free-tier per-minute cap without each call re-implementing the spacing.
_last_request_ts = 0.0


def _throttle() -> None:
    global _last_request_ts
    interval = config.ROIC_MIN_REQUEST_INTERVAL
    if interval <= 0:
        return
    wait = interval - (time.monotonic() - _last_request_ts)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()


def _maybe_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _error_message(resp: Any) -> str:
    try:
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("error"):
            return str(payload["error"])
    except Exception:  # noqa: BLE001 - body may not be JSON
        pass
    return f"HTTP {resp.status_code} from ROIC.ai"


def _get(path: str, params: dict[str, Any] | None = None) -> Any:
    import httpx

    if not config.ROIC_API_KEY:
        raise RoicError("Set ROIC_API_KEY in the environment (see .env.example).")

    query: dict[str, Any] = {"apikey": config.ROIC_API_KEY}
    if params:
        query.update({k: v for k, v in params.items() if v is not None})
    url = f"{config.ROIC_BASE_URL.rstrip('/')}/{path.lstrip('/')}"

    # One retry, reserved for a 429 where we can honor Retry-After.
    for attempt in range(2):
        _throttle()
        resp = httpx.get(url, params=query, timeout=60.0)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429 and attempt == 0:
            retry_after = _maybe_int(resp.headers.get("Retry-After")) or 15
            time.sleep(retry_after + 1)
            continue
        raise RoicError(
            _error_message(resp),
            status=resp.status_code,
            retry_after=_maybe_int(resp.headers.get("Retry-After")),
        )
    raise RoicError("Rate limited by ROIC.ai (429) after one retry.", status=429)


def _to_transcript(data: dict[str, Any]) -> Transcript:
    return Transcript(
        symbol=str(data.get("symbol", "")),
        year=int(data.get("year", 0) or 0),
        quarter=int(data.get("quarter", 0) or 0),
        date=str(data.get("date", "")),
        content=str(data.get("content", "") or ""),
    )


def list_calls(identifier: str, limit: int = 100) -> list[dict[str, Any]]:
    """Available transcripts for a company: [{symbol, year, quarter, date}, ...]."""
    data = _get(f"company/earnings-calls/list/{identifier}", {"limit": limit})
    return list(data) if isinstance(data, list) else []


def latest(identifier: str) -> Transcript:
    """Most recent earnings-call transcript for a company."""
    return _to_transcript(_get(f"company/earnings-calls/latest/{identifier}"))


def get_transcript(identifier: str, year: int, quarter: int) -> Transcript:
    """A specific earnings-call transcript by fiscal year and quarter."""
    data = _get(
        f"company/earnings-calls/transcript/{identifier}",
        {"year": year, "quarter": quarter},
    )
    return _to_transcript(data)
