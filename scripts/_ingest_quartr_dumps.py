#!/usr/bin/env python3
"""Ingest Quartr MCP dump files into healthcare staging by eventId."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "data" / "healthcare_large_cap" / "events_wave_a.json"
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"
DUMP_DIR = Path(
    r"C:\Users\BobbyWhittaker\.cursor\projects"
    r"\c-Users-BobbyWhittaker-OneDrive-Cassius-Capital-Desktop-Earnings-Call-Summarizer"
    r"\agent-tools"
)


def load_catalog() -> dict[int, tuple[str, str]]:
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    out: dict[int, tuple[str, str]] = {}
    for ticker, rows in raw.items():
        for row in rows:
            out[int(row["eventId"])] = (ticker.upper(), str(row["period"]).upper())
    return out


def next_window_index(folder: Path) -> int:
    existing = sorted(int(p.stem) for p in folder.glob("*.json") if p.stem.isdigit())
    return (max(existing) + 1) if existing else 0


def already_has_start(folder: Path, start: float | None) -> bool:
    if start is None:
        return False
    for path in folder.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        paras = data.get("paragraphs") or []
        if not paras:
            continue
        first = paras[0]
        if isinstance(first, dict) and abs(float(first.get("start") or 0) - float(start)) < 0.05:
            return True
    return False


def main() -> int:
    catalog = load_catalog()
    staged = 0
    pending: list[str] = []
    for src in sorted(DUMP_DIR.glob("*.txt")):
        try:
            data = json.loads(src.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict) or "eventId" not in data or "paragraphs" not in data:
            continue
        event_id = int(data["eventId"])
        if event_id not in catalog:
            continue
        ticker, period = catalog[event_id]
        dest_dir = STAGING / ticker / period
        dest_dir.mkdir(parents=True, exist_ok=True)
        paras = data.get("paragraphs") or []
        start = None
        if paras and isinstance(paras[0], dict):
            start = paras[0].get("start")
        if already_has_start(dest_dir, start):
            continue
        idx = next_window_index(dest_dir)
        dest = dest_dir / f"{idx:03d}.json"
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        staged += 1
        nxt = data.get("nextFromTimestamp")
        print(f"STAGED {ticker} {period} {dest.name} eventId={event_id} paras={len(paras)} next={nxt}")
        if nxt is not None:
            pending.append(f"{ticker} {period} eventId={event_id} fromTimestamp={nxt}")
    print(f"STAGED_COUNT={staged}")
    if pending:
        print("PENDING_CONTINUATIONS")
        for line in pending:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
