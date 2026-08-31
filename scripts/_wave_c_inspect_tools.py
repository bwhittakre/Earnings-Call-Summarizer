#!/usr/bin/env python3
import json
from pathlib import Path

tools = Path(
    r"C:\Users\BobbyWhittaker\.cursor\projects"
    r"\c-Users-BobbyWhittaker-OneDrive-Cassius-Capital-Desktop-Earnings-Call-Summarizer"
    r"\agent-tools"
)
want = {33384, 33380, 33379, 33378, 1784, 8148, 13176, 20180}
files = sorted(tools.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)[:50]
for src in files:
    try:
        data = json.loads(src.read_text(encoding="utf-8"))
    except Exception:
        continue
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    if not isinstance(data, dict) or "eventId" not in data:
        continue
    eid = data.get("eventId")
    paras = data.get("paragraphs") or []
    first = paras[0].get("start") if paras else None
    print(
        f"{src.name} EVENT={eid} PARAS={len(paras)} FIRST={first} "
        f"NEXT={data.get('nextFromTimestamp')} WANT={eid in want} SIZE={src.stat().st_size}"
    )
