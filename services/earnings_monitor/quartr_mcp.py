"""Minimal MCP client for Quartr, exposing the calendar as an EventListGateway.

Speaks streamable-HTTP JSON-RPC directly rather than going through a Cursor
session, so the calendar sweep is a normal scheduled process: no editor open,
no agent in the loop. Auth is a bearer token from :mod:`quartr_oauth`.

The tool that lists events is discovered rather than hardcoded. Quartr exposes
several dozen tools and is free to rename them; pinning a guess would fail as a
confusing empty sweep, so ``resolve_events_tool`` picks by inspecting the live
``tools/list`` and can always be overridden with ``QUARTR_MCP_EVENTS_TOOL``.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

LOG = logging.getLogger(__name__)

MCP_URL = os.environ.get("QUARTR_MCP_URL", "https://mcp.quartr.com/mcp")
PROTOCOL_VERSION = "2025-06-18"

MAX_RETRIES = int(os.environ.get("QUARTR_MCP_MAX_RETRIES", "4"))
MAX_RETRY_DELAY = 60.0


def _retry_after_seconds(headers: Any, detail: str, attempt: int) -> float:
    """Prefer the server's own Retry-After; fall back to capped backoff.

    Quartr reports the wait in the JSON body (``retryAfter``) as well as the
    header, and honouring it is what keeps a 45-company sweep inside the limit
    instead of hammering through four doomed retries.
    """
    raw = None
    try:
        raw = headers.get("Retry-After") if headers is not None else None
    except Exception:  # pragma: no cover - defensive
        raw = None
    if raw is None:
        match = re.search(r'"retryAfter"\s*:\s*"?(\d+)', detail)
        raw = match.group(1) if match else None
    try:
        if raw is not None:
            return min(float(raw) + 1.0, MAX_RETRY_DELAY)
    except (TypeError, ValueError):
        pass
    return min(2.0 * (2**attempt), MAX_RETRY_DELAY)


class QuartrMcpError(RuntimeError):
    pass


def _parse_body(content_type: str, raw: str) -> dict[str, Any]:
    """Accept either a JSON body or an SSE stream carrying one JSON-RPC reply."""
    if "text/event-stream" in content_type.lower():
        for line in raw.splitlines():
            if line.startswith("data:"):
                chunk = line[5:].strip()
                if not chunk:
                    continue
                try:
                    payload = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, Mapping) and (
                    "result" in payload or "error" in payload
                ):
                    return dict(payload)
        raise QuartrMcpError(f"no JSON-RPC payload in SSE stream: {raw[:300]}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise QuartrMcpError(f"non-JSON response: {raw[:300]}") from exc


class QuartrMcpClient:
    """JSON-RPC over streamable HTTP. One instance == one MCP session."""

    def __init__(self, access_token: str, *, url: str | None = None):
        if not access_token:
            raise QuartrMcpError("access token is required")
        self.url = url or MCP_URL
        self._token = access_token
        self._session_id: str | None = None
        self._next_id = 0
        self._initialized = False

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _send(self, payload: Mapping[str, Any], *, expect_reply: bool = True):
        body = json.dumps(payload).encode("utf-8")
        for attempt in range(MAX_RETRIES + 1):
            req = urllib.request.Request(
                self.url, data=body, headers=self._headers(), method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    session = resp.headers.get("Mcp-Session-Id")
                    if session:
                        self._session_id = session
                    raw = resp.read().decode("utf-8", "replace")
                    content_type = resp.headers.get("Content-Type", "")
                break
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:400]
                if exc.code in (401, 403):
                    raise QuartrMcpError(
                        f"Quartr rejected the token ({exc.code}). Re-run "
                        f"`host_automation quartr login`. Detail: {detail}"
                    ) from exc
                # Quartr throttles a full-book sweep well before it finishes.
                # Waiting is the correct response: the alternative is a run
                # that silently covers two thirds of the companies.
                if exc.code == 429 and attempt < MAX_RETRIES:
                    delay = _retry_after_seconds(exc.headers, detail, attempt)
                    LOG.info("Quartr rate limited; retrying in %.1fs", delay)
                    time.sleep(delay)
                    continue
                raise QuartrMcpError(f"MCP call failed ({exc.code}): {detail}") from exc
            except OSError as exc:
                if attempt < MAX_RETRIES:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                raise QuartrMcpError(f"MCP call failed: {exc}") from exc
        else:  # pragma: no cover - loop always breaks or raises
            raise QuartrMcpError("MCP call exhausted retries")
        if not expect_reply:
            return None
        message = _parse_body(content_type, raw)
        if "error" in message:
            raise QuartrMcpError(f"MCP error: {message['error']}")
        return message.get("result")

    def _rpc(self, method: str, params: Mapping[str, Any] | None = None):
        self._next_id += 1
        return self._send(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": method,
                "params": dict(params or {}),
            }
        )

    def initialize(self) -> dict[str, Any]:
        result = self._rpc(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "roz-earnings-monitor", "version": "1.0"},
            },
        )
        # Servers may refuse real work until the initialized notification lands.
        self._send(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            expect_reply=False,
        )
        self._initialized = True
        return dict(result or {})

    def _ensure_ready(self) -> None:
        if not self._initialized:
            self.initialize()

    def list_tools(self) -> list[dict[str, Any]]:
        self._ensure_ready()
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params = {"cursor": cursor} if cursor else {}
            result = self._rpc("tools/list", params) or {}
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                return tools

    def call_tool(self, name: str, arguments: Mapping[str, Any]) -> Any:
        self._ensure_ready()
        result = self._rpc("tools/call", {"name": name, "arguments": dict(arguments)})
        return _unwrap_tool_result(result)


def _unwrap_tool_result(result: Any) -> Any:
    """Prefer structuredContent; otherwise decode the text content blocks."""
    if not isinstance(result, Mapping):
        return result
    if result.get("isError"):
        raise QuartrMcpError(f"tool reported an error: {result}")
    if isinstance(result.get("structuredContent"), (Mapping, list)):
        return result["structuredContent"]
    blocks = result.get("content") or []
    texts = [
        str(block.get("text") or "")
        for block in blocks
        if isinstance(block, Mapping) and block.get("type") == "text"
    ]
    joined = "\n".join(t for t in texts if t).strip()
    if not joined:
        return result
    try:
        return json.loads(joined)
    except json.JSONDecodeError:
        return joined


def resolve_events_tool(tools: Sequence[Mapping[str, Any]]) -> str:
    """Pick the tool that lists a company's events.

    Preference order is deliberate: an explicit override, then an exact known
    name, then a scored match. Scoring beats "first tool whose name contains
    events" because Quartr also exposes event *detail* and transcript tools that
    would match that substring and silently return the wrong shape.
    """
    override = os.environ.get("QUARTR_MCP_EVENTS_TOOL", "").strip()
    if override:
        return override
    names = [str(t.get("name") or "") for t in tools if t.get("name")]
    if not names:
        raise QuartrMcpError("Quartr MCP exposed no tools")
    for exact in ("list_events", "get_events", "events", "list_company_events"):
        if exact in names:
            return exact
    best: tuple[int, str] | None = None
    for name in names:
        low = name.lower()
        if "event" not in low:
            continue
        score = 0
        if low.startswith(("list", "get", "search")):
            score += 3
        if "upcoming" in low or "calendar" in low:
            score += 2
        # Detail/transcript endpoints take an event id, not a ticker.
        if any(bad in low for bad in ("transcript", "detail", "by_id", "document")):
            score -= 4
        if best is None or score > best[0]:
            best = (score, name)
    if best is None or best[0] < 0:
        raise QuartrMcpError(
            "could not identify an events tool; set QUARTR_MCP_EVENTS_TOOL. "
            f"Available: {', '.join(sorted(names))}"
        )
    return best[1]


def _rows_from_payload(payload: Any) -> list[dict[str, Any]]:
    """Normalize whatever the tool returned into a list of event rows."""
    if isinstance(payload, list):
        return [dict(row) for row in payload if isinstance(row, Mapping)]
    if isinstance(payload, Mapping):
        for key in ("events", "data", "results", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [dict(row) for row in value if isinstance(row, Mapping)]
        if payload.get("id") is not None or payload.get("eventType") is not None:
            return [dict(payload)]
    return []


def resolve_company_id(payload: Any, ticker: str) -> int | None:
    """Pick the company whose ticker matches exactly.

    Quartr's search is fuzzy and ranks by relevance, so taking the first match
    is unsafe: searching a short ticker returns name-similar companies too, and
    silently arming the wrong company is far worse than skipping one.
    """
    key = ticker.strip().upper()
    matches = _rows_from_payload(payload) or (
        payload.get("matches") if isinstance(payload, Mapping) else None
    ) or []
    for row in matches:
        if not isinstance(row, Mapping):
            continue
        if str(row.get("ticker") or "").strip().upper() == key:
            try:
                return int(row.get("id"))
            except (TypeError, ValueError):
                return None
    return None


class QuartrMcpGateway:
    """``EventListGateway`` backed by the Quartr MCP.

    Satisfies the same ``list_events(*, ticker)`` contract as the JSON-dump
    gateways, so ``publish_calendar`` cannot tell the difference and the whole
    publish path stays covered by its existing tests.

    Quartr's ``list_events`` takes a ``companyId``, not a ticker, so each name
    costs a ``search_companies`` lookup first. Those are cached for the life of
    the sweep -- 45 tickers would otherwise mean 45 avoidable round trips.

    ``expand`` is required by the tool and must include ``contentDates``: the
    manifest builder reads the report/audio timestamps from it, and without it
    every row would parse into a manifest with no call time.
    """

    #: Wide by default; ``publish_calendar`` applies the real horizon. Reaching
    #: past one quarter is what lets the next call be scheduled on COMPLETE.
    DEFAULT_LOOKBACK_DAYS = 7
    DEFAULT_LOOKAHEAD_DAYS = 150

    def __init__(
        self,
        client: QuartrMcpClient,
        *,
        tool_name: str | None = None,
        lookback_days: int | None = None,
        lookahead_days: int | None = None,
        extra_arguments: Mapping[str, Any] | None = None,
    ):
        self.client = client
        self._tool_name = tool_name
        self._extra = dict(extra_arguments or {})
        self._lookback = (
            self.DEFAULT_LOOKBACK_DAYS if lookback_days is None else lookback_days
        )
        self._lookahead = (
            self.DEFAULT_LOOKAHEAD_DAYS if lookahead_days is None else lookahead_days
        )
        self._company_ids: dict[str, int | None] = {}

    @property
    def tool_name(self) -> str:
        if self._tool_name is None:
            self._tool_name = resolve_events_tool(self.client.list_tools())
            LOG.info("Using Quartr events tool: %s", self._tool_name)
        return self._tool_name

    def company_id(self, ticker: str) -> int | None:
        key = ticker.strip().upper()
        if key not in self._company_ids:
            try:
                payload = self.client.call_tool(
                    "search_companies", {"query": key, "perPage": 10}
                )
                self._company_ids[key] = resolve_company_id(payload, key)
            except QuartrMcpError as exc:
                LOG.warning("Quartr company lookup failed for %s: %s", key, exc)
                self._company_ids[key] = None
        return self._company_ids[key]

    def list_events(self, *, ticker: str) -> Sequence[Mapping[str, Any]]:
        key = ticker.strip().upper()
        company_id = self.company_id(key)
        if company_id is None:
            LOG.warning("No exact Quartr company match for %s; skipping", key)
            return ()
        now = datetime.now(timezone.utc)
        arguments: dict[str, Any] = {
            "companyId": company_id,
            # Required by the tool; contentDates carries the call/report times.
            "expand": ["contentDates"],
            "startDate": (now - timedelta(days=self._lookback)).date().isoformat(),
            "endDate": (now + timedelta(days=self._lookahead)).date().isoformat(),
            "order": "asc",
            "limit": 200,
            **self._extra,
        }
        try:
            payload = self.client.call_tool(self.tool_name, arguments)
        except QuartrMcpError as exc:
            # One bad ticker must not abandon the other 44.
            LOG.warning("Quartr events lookup failed for %s: %s", key, exc)
            return ()
        rows = _rows_from_payload(payload)
        for row in rows:
            row.setdefault("ticker", key)
        return rows
