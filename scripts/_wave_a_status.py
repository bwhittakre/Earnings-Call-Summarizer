#!/usr/bin/env python3
"""Report wave-A staging completeness."""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "data" / "healthcare_large_cap" / "events_wave_a.json"
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"
OUT = REPO / "Structured Narrative" / "transcripts_raw"


def last_next(folder: Path):
    windows = sorted(p for p in folder.glob("*.json") if p.stem.isdigit())
    if not windows:
        return None, 0
    data = json.loads(windows[-1].read_text(encoding="utf-8"))
    return data.get("nextFromTimestamp"), len(windows)


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    for ticker, rows in catalog.items():
        missing = []
        pending = []
        complete = []
        written = []
        for row in rows:
            period = row["period"]
            event_id = row["eventId"]
            dest = OUT / f"{ticker}_{period}.txt"
            if dest.exists() and dest.stat().st_size > 2000:
                written.append(period)
                continue
            folder = STAGING / ticker / period
            nxt, nwin = last_next(folder)
            if nwin == 0:
                missing.append(f"{period} eventId={event_id}")
            elif nxt is not None:
                pending.append(f"{period} eventId={event_id} fromTimestamp={nxt}")
            else:
                complete.append(period)
        print(f"== {ticker} ==")
        print(f"written={len(written)} staged_complete={len(complete)} pending={len(pending)} missing={len(missing)}")
        for line in pending:
            print(f"  PENDING {line}")
        for line in missing:
            print(f"  MISSING {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
