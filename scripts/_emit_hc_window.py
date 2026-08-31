#!/usr/bin/env python3
"""Write a slim healthcare window from a JSON list or full read_transcript object."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ticker, period, window, event_id, src = (
    sys.argv[1],
    sys.argv[2],
    int(sys.argv[3]),
    int(sys.argv[4]),
    Path(sys.argv[5]),
)
data = json.loads(src.read_text(encoding="utf-8"))
if isinstance(data, list):
    raw_paras = data
    nxt = None
else:
    raw_paras = data.get("paragraphs") or []
    nxt = data.get("nextFromTimestamp")
paras = []
for item in raw_paras:
    if not isinstance(item, dict):
        continue
    text = str(item.get("text") or "").strip()
    if not text:
        continue
    row = {"text": text}
    speaker = str(item.get("speakerName") or item.get("speaker") or "").strip()
    if speaker:
        row["speakerName"] = speaker
    if item.get("start") is not None:
        row["start"] = item.get("start")
    paras.append(row)
out = Path("data/healthcare_large_cap/windows") / ticker / period / f"{window:03d}.json"
out.parent.mkdir(parents=True, exist_ok=True)
payload = {"eventId": event_id, "nextFromTimestamp": nxt, "paragraphs": paras}
out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
print(f"WROTE={out} paras={len(paras)} next={nxt}")
