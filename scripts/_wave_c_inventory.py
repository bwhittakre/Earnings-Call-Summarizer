#!/usr/bin/env python3
import json
from pathlib import Path

STAGING = Path(__file__).resolve().parents[1] / "data" / "healthcare_large_cap" / "windows"
for ticker in ["GILD", "VRTX", "MDT"]:
    root = STAGING / ticker
    print("===", ticker)
    complete = done = need = 0
    for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
        p0 = d / "000.json"
        p1 = d / "001.json"
        if not p0.exists():
            print("NO000", d.name)
            continue
        body = json.loads(p0.read_text(encoding="utf-8"))
        nxt = body.get("nextFromTimestamp")
        eid = body.get("eventId")
        if nxt is None:
            complete += 1
            print(f"OK {d.name} eid={eid} NEXT=None")
        elif p1.exists():
            done += 1
            print(f"P2 {d.name} eid={eid} FROM={nxt}")
        else:
            need += 1
            print(f"NEED {d.name} eid={eid} FROM={nxt}")
    print(f"SUM {ticker} complete={complete} p2done={done} p2need={need}")
