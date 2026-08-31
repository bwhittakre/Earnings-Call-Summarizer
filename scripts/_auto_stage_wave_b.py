#!/usr/bin/env python3
"""Stage newest agent-tools read_transcript dumps into healthcare windows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CATALOG = REPO / "data" / "healthcare_large_cap" / "wave_b_events.json"
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"
AGENT_TOOLS = Path(
    r"C:\Users\BobbyWhittaker\.cursor\projects\c-Users-BobbyWhittaker-OneDrive-Cassius-Capital-Desktop-Earnings-Call-Summarizer\agent-tools"
)


def main() -> int:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    lookup: dict[int, tuple[str, str]] = {}
    for ticker, block in catalog.items():
        for row in block.get("available") or []:
            lookup[int(row["eventId"])] = (ticker, str(row["period"]))

    staged = 0
    for path in sorted(AGENT_TOOLS.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)[:80]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or "paragraphs" not in data:
            continue
        eid = data.get("eventId")
        if eid not in lookup:
            continue
        ticker, period = lookup[int(eid)]
        dest_dir = STAGING / ticker / period
        dest_dir.mkdir(parents=True, exist_ok=True)
        paras = data.get("paragraphs") or []
        starts = [p.get("start") for p in paras if isinstance(p, dict) and p.get("start") is not None]
        min_start = min(starts) if starts else 0
        index = 0 if float(min_start) < 50 else 1
        dest = dest_dir / f"{index:03d}.json"
        if dest.exists():
            continue
        dest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        nxt = data.get("nextFromTimestamp")
        print(f"{ticker} {period} {dest.name} event={eid} npar={len(paras)} next={nxt}")
        staged += 1
    print(f"STAGED={staged}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
