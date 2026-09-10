"""MCP pull contract for new-company onboard (2016-Q1 or all available).

Docker cannot call Cursor Quartr MCP. The agent pulls first, writes files,
then onboard runs with ``--skip-pull``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

LOOKBACK_START_PERIOD = "2016-Q1"
CONF_DIRNAME = Path("data") / "conf_transcripts"
MANIFEST_NAME = "manifest.json"


def pull_checklist(*, ticker: str) -> dict[str, Any]:
    """Describe the MCP pull the agent must finish before ``--skip-pull``."""
    key = ticker.strip().upper()
    return {
        "ticker": key,
        "lookback_start": LOOKBACK_START_PERIOD,
        "lookback_rule": (
            f"Target {LOOKBACK_START_PERIOD} through today. If Quartr has no "
            "history that far back, pull every available event. Do not invent "
            "earlier periods and do not stop at a 3y/10y onboard window."
        ),
        "source": "quartr_mcp",
        "steps": [
            "search_companies",
            "list_events (earnings + conferences + investor days + other meetings with transcripts)",
            "read_transcript (+ section=qna when nextFromTimestamp is set)",
        ],
        "earnings_path": f"Structured Narrative/transcripts_raw/{key}_FY….txt",
        "conference_dir": str(CONF_DIRNAME / key),
        "conference_manifest": str(CONF_DIRNAME / key / MANIFEST_NAME),
        "onboard_after": "--skip-pull --research-sector independent",
    }


def conference_dir(repo_root: Path, ticker: str) -> Path:
    return Path(repo_root) / CONF_DIRNAME / ticker.strip().upper()


def load_conference_manifest(repo_root: Path, ticker: str) -> dict[str, Any]:
    path = conference_dir(repo_root, ticker) / MANIFEST_NAME
    if not path.is_file():
        return {"ticker": ticker.strip().upper(), "events": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ticker": ticker.strip().upper(), "events": []}
    if not isinstance(payload, dict):
        return {"ticker": ticker.strip().upper(), "events": []}
    payload.setdefault("ticker", ticker.strip().upper())
    payload.setdefault("events", [])
    return payload


def save_conference_manifest(
    repo_root: Path, ticker: str, payload: dict[str, Any]
) -> Path:
    folder = conference_dir(repo_root, ticker)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / MANIFEST_NAME
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def write_conference_transcript(
    repo_root: Path,
    *,
    ticker: str,
    event_id: int | str,
    event_date: str,
    event_name: str,
    payload: dict[str, Any] | None = None,
    source_path: str | Path | None = None,
) -> Path:
    """Write ``{eventId}.json`` (or copy) and upsert the conference manifest."""
    folder = conference_dir(repo_root, ticker)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{event_id}.json"
    if source_path is not None:
        text = Path(source_path).read_text(encoding="utf-8")
        dest.write_text(text, encoding="utf-8")
    elif payload is not None:
        dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    elif not dest.is_file():
        dest.write_text("{}\n", encoding="utf-8")

    manifest = load_conference_manifest(repo_root, ticker)
    events = [
        event
        for event in (manifest.get("events") or [])
        if str(event.get("event_id")) != str(event_id)
    ]
    events.append(
        {
            "event_id": int(event_id) if str(event_id).isdigit() else event_id,
            "date": str(event_date).strip(),
            "name": str(event_name).strip(),
            "path": dest.name,
        }
    )
    events.sort(key=lambda item: str(item.get("date") or ""))
    manifest["ticker"] = ticker.strip().upper()
    manifest["events"] = events
    save_conference_manifest(repo_root, ticker, manifest)
    return dest


def discover_conference_events(repo_root: Path, ticker: str) -> list[dict[str, Any]]:
    """Union manifest rows with on-disk ``{eventId}.json`` files."""
    folder = conference_dir(repo_root, ticker)
    manifest = load_conference_manifest(repo_root, ticker)
    by_id: dict[str, dict[str, Any]] = {}
    for event in manifest.get("events") or []:
        key = str(event.get("event_id") or "").strip()
        if not key:
            continue
        row = dict(event)
        rel = str(row.get("path") or f"{key}.json")
        row["path"] = str(folder / Path(rel).name)
        by_id[key] = row
    if folder.is_dir():
        for path in folder.glob("*.json"):
            if path.name == MANIFEST_NAME:
                continue
            key = path.stem
            row = by_id.get(key) or {
                "event_id": int(key) if key.isdigit() else key,
                "date": "",
                "name": "",
                "path": str(path),
            }
            row["path"] = str(path)
            by_id[key] = row
    return sorted(by_id.values(), key=lambda item: str(item.get("date") or item.get("event_id")))
