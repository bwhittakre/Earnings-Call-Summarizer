"""Load Quartr timed transcript JSON + event anchors."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Paragraph:
    index: int
    start_sec: float
    end_sec: float
    speaker: str
    speaker_role: str | None
    text: str
    url: str | None = None


@dataclass(frozen=True)
class EventAnchors:
    ticker: str
    fiscal_period: str
    event_id: int | str | None
    call_at: datetime
    report_at: datetime | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class TimedTranscript:
    event_id: int | str | None
    document_id: int | str | None
    paragraphs: list[Paragraph]
    first_start_sec: float | None
    last_end_sec: float | None
    raw: dict[str, Any]


def load_anchors(path: Path | str) -> EventAnchors:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    call_at = _parse_utc(raw.get("call_at"))
    if call_at is None:
        raise ValueError(f"anchors missing call_at: {path}")
    report_at = _parse_utc(raw.get("report_at"))
    ticker = str(raw.get("ticker") or "").upper()
    fiscal_period = str(raw.get("fiscal_period") or "").upper()
    return EventAnchors(
        ticker=ticker,
        fiscal_period=fiscal_period,
        event_id=raw.get("eventId"),
        call_at=call_at,
        report_at=report_at,
        raw=raw,
    )


def load_transcript(path: Path | str) -> TimedTranscript:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    paragraphs_raw = raw.get("paragraphs") or []
    paragraphs: list[Paragraph] = []
    for i, row in enumerate(paragraphs_raw):
        start = row.get("start")
        end = row.get("end")
        if start is None:
            continue
        paragraphs.append(
            Paragraph(
                index=i,
                start_sec=float(start),
                end_sec=float(end if end is not None else start),
                speaker=str(row.get("speaker") or ""),
                speaker_role=row.get("speakerRole"),
                text=str(row.get("text") or ""),
                url=row.get("url"),
            )
        )
    paragraphs.sort(key=lambda p: (p.start_sec, p.index))
    return TimedTranscript(
        event_id=raw.get("eventId"),
        document_id=raw.get("documentId"),
        paragraphs=paragraphs,
        first_start_sec=float(raw["first_start_sec"]) if raw.get("first_start_sec") is not None else (
            paragraphs[0].start_sec if paragraphs else None
        ),
        last_end_sec=float(raw["last_end_sec"]) if raw.get("last_end_sec") is not None else (
            paragraphs[-1].end_sec if paragraphs else None
        ),
        raw=raw,
    )
