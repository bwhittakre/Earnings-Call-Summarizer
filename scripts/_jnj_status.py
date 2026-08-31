#!/usr/bin/env python3
from __future__ import annotations
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "data" / "healthcare_large_cap" / "events_wave_a.json"
STAGING = REPO / "data" / "healthcare_large_cap" / "windows" / "JNJ"

catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["JNJ"]
done = []
pending = []
for row in catalog:
    period = row["period"]
    event_id = row["eventId"]
    folder = STAGING / period
    windows = sorted(p for p in folder.glob("*.json") if p.stem.isdigit()) if folder.is_dir() else []
    if not windows:
        pending.append(f"{period} eventId={event_id} MISSING")
        continue
    data = json.loads(windows[-1].read_text(encoding="utf-8"))
    nxt = data.get("nextFromTimestamp")
    if nxt is None:
        done.append(period)
    else:
        pending.append(f"{period} eventId={event_id} fromTimestamp={nxt}")
print(f"complete={len(done)} pending={len(pending)}")
print("DONE=" + ",".join(done))
for line in pending:
    print("PENDING " + line)
