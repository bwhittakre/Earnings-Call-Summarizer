#!/usr/bin/env python3
"""Write a slim PFE page-2 window from a JSON list of {speakerName,text,start?}."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ticker, period, event_id, src = sys.argv[1], sys.argv[2], int(sys.argv[3]), Path(sys.argv[4])
paras = json.loads(src.read_text(encoding="utf-8"))
out = Path("data/healthcare_large_cap/windows") / ticker / period / "001.json"
out.parent.mkdir(parents=True, exist_ok=True)
payload = {"eventId": event_id, "nextFromTimestamp": None, "paragraphs": paras}
out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
print(f"WROTE={out} paras={len(paras)}")
