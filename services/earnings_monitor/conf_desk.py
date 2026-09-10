"""Ingest on-disk Quartr MCP conference transcripts into the Claims Desk."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .onboard_pull import discover_conference_events

LOG = logging.getLogger(__name__)


def _conf_cue_path(repo_root: Path, ticker: str) -> Path:
    return Path(repo_root) / "data" / f"desk_conf_cue_{ticker.strip().upper()}.json"


def _already_ingested(repo_root: Path, ticker: str, event_id: Any) -> bool:
    path = _conf_cue_path(repo_root, ticker)
    if not path.is_file():
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    wanted = str(event_id)
    for event in payload.get("events") or []:
        if str(event.get("event_id")) != wanted:
            continue
        excerpts = event.get("excerpts") or []
        return bool(excerpts) or bool(event.get("ingested_at"))
    return False


def ingest_on_disk_conferences(
    *,
    repo_root: Path,
    ticker: str,
    dry_run: bool = False,
    extract_only: bool = True,
) -> dict[str, Any]:
    """Seed desk cues from ``data/conf_transcripts/{TICKER}/`` (MCP files).

    Uses ``--transcript-file`` only — never Quartr REST. Events without a
    manifest date are skipped (the pull checklist must write the manifest).
    """
    ticker_key = ticker.strip().upper()
    events = discover_conference_events(repo_root, ticker_key)
    ingested: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if dry_run:
        return {
            "ticker": ticker_key,
            "discovered": len(events),
            "ingested": ingested,
            "skipped": [{"event_id": e.get("event_id"), "reason": "dry_run"} for e in events],
            "dry_run": True,
        }

    from scripts._desk_conf_ingest import ingest_conference

    for event in events:
        event_id = event.get("event_id")
        date = str(event.get("date") or "").strip()
        name = str(event.get("name") or "").strip() or f"event {event_id}"
        path = Path(str(event.get("path") or ""))
        if not date:
            skipped.append({"event_id": event_id, "reason": "missing_date"})
            continue
        if not path.is_file():
            skipped.append({"event_id": event_id, "reason": "missing_transcript"})
            continue
        if _already_ingested(repo_root, ticker_key, event_id):
            skipped.append({"event_id": event_id, "reason": "already_ingested"})
            continue
        try:
            rows = ingest_conference(
                ticker_key,
                event_id,
                date,
                name,
                extract_only=extract_only,
                transcript_file=path,
            )
            ingested.append(
                {
                    "event_id": event_id,
                    "date": date,
                    "name": name,
                    "n_rows": len(rows),
                }
            )
        except Exception as exc:  # noqa: BLE001 — onboard must continue
            LOG.warning(
                "Conference ingest failed for %s event %s: %s",
                ticker_key,
                event_id,
                exc,
            )
            skipped.append({"event_id": event_id, "reason": str(exc)})
    return {
        "ticker": ticker_key,
        "discovered": len(events),
        "ingested": ingested,
        "skipped": skipped,
        "dry_run": False,
    }
