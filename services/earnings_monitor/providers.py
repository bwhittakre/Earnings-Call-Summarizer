"""Provider interfaces and adapters; network access is injected by callers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .models import EarningsEvent, TranscriptDocument


class EventProvider(ABC):
    @abstractmethod
    def list_events(
        self, tickers: Iterable[str], *, since: datetime, until: datetime
    ) -> list[EarningsEvent]:
        """Return known earnings events within an inclusive UTC window."""


class TranscriptProvider(ABC):
    @abstractmethod
    def get_transcript(self, event: EarningsEvent) -> TranscriptDocument | None:
        """Return the latest provider snapshot, or None when unavailable."""


class QuartrGateway(Protocol):
    """Small injectable boundary implemented by an API or MCP client."""

    def search_events(
        self, *, tickers: list[str], since: str, until: str
    ) -> Iterable[Mapping[str, Any]]: ...

    def fetch_transcript(self, *, event_id: str) -> Mapping[str, Any] | None: ...


def _parse_datetime(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _first_value(value: Any, *keys: str) -> Any:
    if isinstance(value, Mapping):
        for key in keys:
            if value.get(key) is not None:
                return value[key]
    return None


def _content_date(row: Mapping[str, Any], kind: str) -> Any:
    dates = row.get("contentDates")
    keys = (
        ("report", "release", "reportDate", "releaseDate", "publishedAt")
        if kind == "report"
        else ("call", "event", "callDate", "eventDate", "startDate")
    )
    direct = _first_value(dates, *keys)
    if direct is not None:
        return direct
    if isinstance(dates, list):
        for item in dates:
            if not isinstance(item, Mapping):
                continue
            label = str(
                item.get("contentType") or item.get("type") or item.get("kind") or ""
            ).lower()
            is_match = (
                kind in label
                or (kind == "report" and "release" in label)
                or (kind == "call" and label in {"audio", "webcast"})
            )
            if is_match:
                return _first_value(item, "date", "value", "datetime", "startDate")
    return None


def _fiscal_period(row: Mapping[str, Any]) -> str:
    explicit = row.get("fiscal_period") or row.get("period")
    if explicit:
        return str(explicit).upper()
    year = row.get("fiscalYear")
    quarter = row.get("fiscalQuarter")
    if not quarter:
        event_type = str(row.get("eventType") or "")
        match = re.fullmatch(r"q_?([1-4])", event_type, re.IGNORECASE)
        quarter = match.group(1) if match else None
    if not quarter:
        match = re.search(r"\bQ([1-4])\b", str(row.get("title") or ""), re.IGNORECASE)
        quarter = match.group(1) if match else None
    if year and quarter:
        return f"FY{year}-Q{str(quarter).upper().removeprefix('Q')}"
    return ""


class QuartrAdapter(EventProvider, TranscriptProvider):
    """Normalizes a caller-supplied Quartr API/MCP gateway."""

    def __init__(self, gateway: QuartrGateway):
        self.gateway = gateway

    def list_events(
        self, tickers: Iterable[str], *, since: datetime, until: datetime
    ) -> list[EarningsEvent]:
        requested = {ticker.upper() for ticker in tickers}
        rows = self.gateway.search_events(
            tickers=sorted(requested), since=since.isoformat(), until=until.isoformat()
        )
        events: list[EarningsEvent] = []
        for row in rows:
            company = row.get("company")
            ticker = str(
                row.get("ticker")
                or row.get("symbol")
                or _first_value(company, "ticker", "symbol")
                or ""
            ).upper()
            if ticker not in requested:
                continue
            event_id = str(row.get("event_id") or row.get("id") or "")
            period = _fiscal_period(row)
            generic = row.get("scheduled_at") or row.get("date")
            report_at = _content_date(row, "report") or row.get("report_at") or generic
            call_at = _content_date(row, "call") or row.get("call_at") or generic or report_at
            if not event_id or not period or not report_at or not call_at:
                continue
            events.append(
                EarningsEvent(
                    provider_event_id=event_id,
                    ticker=ticker,
                    fiscal_period=period,
                    report_at=_parse_datetime(report_at),
                    call_at=_parse_datetime(call_at),
                    title=str(row.get("title") or ""),
                    source_url=row.get("url"),
                )
            )
        return sorted(events, key=lambda event: event.scheduled_at)

    def get_transcript(self, event: EarningsEvent) -> TranscriptDocument | None:
        row = self.gateway.fetch_transcript(event_id=event.provider_event_id)
        if not row:
            return None
        transcript: Any = row.get("transcript") or row
        if isinstance(transcript, list):
            transcript = transcript[0] if transcript else {}
        if isinstance(transcript, str):
            content = transcript.strip()
            transcript = {}
        else:
            content = str(_first_value(transcript, "content", "text", "body") or "").strip()
        if not content:
            return None
        return TranscriptDocument(
            ticker=event.ticker,
            fiscal_period=event.fiscal_period,
            content=content,
            source_name="quartr",
            source_id=str(
                _first_value(transcript, "documentId", "document_id", "id")
                or row.get("document_id")
                or row.get("id")
                or event.provider_event_id
            ),
            observed_at=_parse_datetime(
                _first_value(transcript, "updatedAt", "updated_at", "publishedAt")
                or row.get("updated_at")
                or datetime.now(timezone.utc)
            ),
            source_url=_first_value(transcript, "url", "sourceUrl") or row.get("url") or event.source_url,
        )


_FILENAME = re.compile(r"(?P<ticker>[A-Za-z0-9]+)[-_]FY(?P<year>\d{4})[-_ ]?Q(?P<quarter>[1-4])", re.I)
_HEADER = re.compile(r"^#\s*([^:]+):\s*(.*)$")


class LocalInboxProvider(EventProvider, TranscriptProvider):
    """Offline fallback that treats inbox files as discovered events."""

    def __init__(
        self,
        inbox: Path | str,
        *,
        clock: Callable[[], datetime] | None = None,
    ):
        self.inbox = Path(inbox)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def _files(self) -> list[Path]:
        return sorted(self.inbox.glob("*.txt")) if self.inbox.is_dir() else []

    @staticmethod
    def _metadata(path: Path) -> tuple[str, str] | None:
        ticker = period = ""
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[:20]
        except OSError:
            return None
        for line in lines:
            match = _HEADER.match(line)
            if not match:
                continue
            key, value = match.group(1).strip().lower(), match.group(2).strip()
            if key == "company":
                ticker = value.upper()
            elif key == "period":
                normalized = re.sub(r"\s+", "-", value.upper().replace("FY ", "FY"))
                period = normalized if re.fullmatch(r"FY\d{4}-Q[1-4]", normalized) else period
        fallback = _FILENAME.search(path.stem)
        if fallback:
            ticker = ticker or fallback.group("ticker").upper()
            period = period or f"FY{fallback.group('year')}-Q{fallback.group('quarter')}"
        return (ticker, period) if ticker and period else None

    def list_events(
        self, tickers: Iterable[str], *, since: datetime, until: datetime
    ) -> list[EarningsEvent]:
        requested = {ticker.upper() for ticker in tickers}
        result: list[EarningsEvent] = []
        for path in self._files():
            metadata = self._metadata(path)
            if not metadata or metadata[0] not in requested:
                continue
            observed = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if since <= observed <= until:
                result.append(
                    EarningsEvent(
                        provider_event_id=f"local:{path.resolve()}",
                        ticker=metadata[0],
                        fiscal_period=metadata[1],
                        report_at=observed,
                        call_at=observed,
                        title=f"{metadata[0]} {metadata[1]} earnings call",
                        source_url=str(path),
                    )
                )
        return result

    def get_transcript(self, event: EarningsEvent) -> TranscriptDocument | None:
        path = Path(event.provider_event_id.removeprefix("local:"))
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace")
        body = "\n".join(line for line in text.splitlines() if not _HEADER.match(line)).strip()
        if not body:
            return None
        return TranscriptDocument(
            ticker=event.ticker,
            fiscal_period=event.fiscal_period,
            content=body,
            source_name="local",
            source_id=str(path.resolve()),
            observed_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
            source_url=str(path),
        )
