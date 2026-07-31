"""Provider interfaces and adapters; network access is injected by callers."""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from .models import EarningsEvent, TranscriptDocument, TranscriptStatus

LOG = logging.getLogger(__name__)


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


class ManualEventProvider(EventProvider):
    """Event discovery is disabled; events are armed explicitly through the CLI."""

    def list_events(
        self, tickers: Iterable[str], *, since: datetime, until: datetime
    ) -> list[EarningsEvent]:
        return []


def _parse_datetime(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _required_datetime(value: Any, field: str) -> datetime:
    if not isinstance(value, (str, datetime)):
        raise ValueError(f"{field} must be an ISO-8601 timestamp")
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(
        value.replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _required_string(row: Mapping[str, Any], field: str) -> str:
    value = row.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _required_url(row: Mapping[str, Any], field: str = "source_url") -> str:
    value = _required_string(row, field)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field} must be an absolute HTTP(S) URL")
    return value


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
            provider_event_id=event.provider_event_id,
        )


_FILENAME = re.compile(r"(?P<ticker>[A-Za-z0-9]+)[-_]FY(?P<year>\d{4})[-_ ]?Q(?P<quarter>[1-4])", re.I)
_HEADER = re.compile(r"^#\s*([^:]+):\s*(.*)$")
EVENT_MANIFEST_SUFFIX = ".event.json"
TRANSCRIPT_BUNDLE_SUFFIX = ".transcript.json"


def parse_event_manifest(row: Mapping[str, Any]) -> EarningsEvent:
    """Validate the durable v1 assisted-event manifest contract."""
    if row.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    source_url = _required_url(row)
    return EarningsEvent(
        provider_event_id=_required_string(row, "provider_event_id"),
        ticker=_required_string(row, "ticker"),
        fiscal_period=_required_string(row, "fiscal_period"),
        report_at=_required_datetime(row.get("report_at"), "report_at"),
        call_at=_required_datetime(row.get("call_at"), "call_at"),
        title=_required_string(row, "title"),
        source_url=source_url,
    )


class WatchedEventManifestProvider(EventProvider):
    """Read atomically-delivered Quartr-assisted event manifests from a directory."""

    def __init__(self, manifest_dir: Path | str):
        self.manifest_dir = Path(manifest_dir)

    def list_events(
        self, tickers: Iterable[str], *, since: datetime, until: datetime
    ) -> list[EarningsEvent]:
        requested = {ticker.strip().upper() for ticker in tickers}
        by_id: dict[str, EarningsEvent] = {}
        if not self.manifest_dir.is_dir():
            return []

        def order_key(path: Path) -> tuple[int, str]:
            try:
                return path.stat().st_mtime_ns, path.name
            except OSError:
                return 0, path.name

        paths = sorted(
            self.manifest_dir.glob(f"*{EVENT_MANIFEST_SUFFIX}"),
            key=order_key,
        )
        for path in paths:
            try:
                row = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(row, Mapping):
                    raise ValueError("manifest root must be an object")
                event = parse_event_manifest(row)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
                LOG.warning("Ignoring malformed event manifest %s: %s", path, exc)
                continue
            if event.ticker not in requested:
                continue
            by_id[event.provider_event_id] = event
        return sorted(
            (
                event
                for event in by_id.values()
                if since <= event.scheduled_at <= until
            ),
            key=lambda event: event.scheduled_at,
        )


def _normalize_speaker(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def parse_transcript_bundle(row: Mapping[str, Any]) -> TranscriptDocument:
    """Validate and normalize the durable v1 transcript bundle contract."""
    if row.get("schema_version") != 1:
        raise ValueError("schema_version must be 1")
    status = TranscriptStatus(_required_string(row, "status").lower())
    raw_speaker_text = row.get("speaker_text")
    if not isinstance(raw_speaker_text, list) or not raw_speaker_text:
        raise ValueError("speaker_text must be a non-empty list")
    rendered: list[str] = []
    for index, segment in enumerate(raw_speaker_text):
        if not isinstance(segment, Mapping):
            raise ValueError(f"speaker_text[{index}] must be an object")
        speaker = _normalize_speaker(_required_string(segment, "speaker"))
        text = _normalize_speaker(_required_string(segment, "text"))
        rendered.append(f"{speaker}: {text}")
    return TranscriptDocument(
        ticker=_required_string(row, "ticker"),
        fiscal_period=_required_string(row, "fiscal_period"),
        content="\n\n".join(rendered),
        source_name="quartr-assisted",
        source_id=_required_string(row, "provider_document_id"),
        observed_at=_required_datetime(row.get("observed_at"), "observed_at"),
        source_url=_required_url(row),
        provider_event_id=_required_string(row, "provider_event_id"),
        status=status,
    )


def _write_json_atomic(path: Path | str, row: Mapping[str, Any]) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=destination.parent,
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(dict(row), handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    try:
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination


def write_event_manifest_atomic(path: Path | str, row: Mapping[str, Any]) -> Path:
    """Validate and atomically publish an assisted event manifest."""
    destination = Path(path)
    if not destination.name.endswith(EVENT_MANIFEST_SUFFIX):
        raise ValueError(f"event manifest must end with {EVENT_MANIFEST_SUFFIX}")
    parse_event_manifest(row)
    return _write_json_atomic(destination, row)


def write_transcript_bundle_atomic(path: Path | str, row: Mapping[str, Any]) -> Path:
    """Validate and atomically publish a transcript bundle for the watcher."""
    destination = Path(path)
    if not destination.name.endswith(TRANSCRIPT_BUNDLE_SUFFIX):
        raise ValueError(f"transcript bundle must end with {TRANSCRIPT_BUNDLE_SUFFIX}")
    parse_transcript_bundle(row)
    return _write_json_atomic(destination, row)


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

    def _text_files(self) -> list[Path]:
        return sorted(self.inbox.glob("*.txt")) if self.inbox.is_dir() else []

    def _bundle_files(self) -> list[Path]:
        return (
            sorted(self.inbox.glob(f"*{TRANSCRIPT_BUNDLE_SUFFIX}"))
            if self.inbox.is_dir()
            else []
        )

    def _files(self) -> list[Path]:
        return sorted([*self._text_files(), *self._bundle_files()])

    @staticmethod
    def _text_metadata(path: Path) -> tuple[str, str] | None:
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

    @staticmethod
    def _read_bundle(path: Path) -> TranscriptDocument | None:
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(row, Mapping):
                raise ValueError("bundle root must be an object")
            return parse_transcript_bundle(row)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            LOG.warning("Ignoring malformed transcript bundle %s: %s", path, exc)
            return None

    @classmethod
    def _metadata(cls, path: Path) -> tuple[str, str] | None:
        if path.name.endswith(TRANSCRIPT_BUNDLE_SUFFIX):
            document = cls._read_bundle(path)
            return (document.ticker, document.fiscal_period) if document else None
        return cls._text_metadata(path)

    @classmethod
    def _read_text(cls, path: Path) -> TranscriptDocument | None:
        metadata = cls._text_metadata(path)
        if metadata is None:
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            observed = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return None
        body = "\n".join(line for line in text.splitlines() if not _HEADER.match(line)).strip()
        if not body:
            return None
        return TranscriptDocument(
            ticker=metadata[0],
            fiscal_period=metadata[1],
            content=body,
            source_name="local",
            source_id=str(path.resolve()),
            observed_at=observed,
            source_url=str(path),
        )

    @classmethod
    def _read_document(cls, path: Path) -> TranscriptDocument | None:
        if path.name.endswith(TRANSCRIPT_BUNDLE_SUFFIX):
            return cls._read_bundle(path)
        return cls._read_text(path)

    def list_events(
        self, tickers: Iterable[str], *, since: datetime, until: datetime
    ) -> list[EarningsEvent]:
        requested = {ticker.upper() for ticker in tickers}
        result: list[EarningsEvent] = []
        for path in self._files():
            metadata = self._metadata(path)
            if not metadata or metadata[0] not in requested:
                continue
            document = self._read_document(path)
            if document is None:
                continue
            observed = document.observed_at
            if since <= observed <= until:
                result.append(
                    EarningsEvent(
                        provider_event_id=document.provider_event_id or f"local:{path.resolve()}",
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
        if event.provider_event_id.startswith("local:"):
            path = Path(event.provider_event_id.removeprefix("local:"))
            return self._read_document(path) if path.is_file() else None
        else:
            documents = [
                document
                for path in self._files()
                if (document := self._read_document(path)) is not None
                and (
                    document.provider_event_id == event.provider_event_id
                    or (document.ticker, document.fiscal_period)
                    == (event.ticker, event.fiscal_period)
                )
            ]
        if not documents:
            return None
        return max(
            documents,
            key=lambda document: (
                document.status == TranscriptStatus.FINAL,
                document.observed_at,
                document.source_id,
            ),
        )
