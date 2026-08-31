#!/usr/bin/env python3
"""Write one slim window JSON from stdin or --src (eventId + paragraphs only)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"


def slim(payload: dict) -> dict:
    paras = []
    for p in payload.get("paragraphs") or []:
        paras.append({"speakerName": p.get("speakerName") or "", "text": p.get("text") or ""})
    return {"eventId": payload["eventId"], "isLive": False, "paragraphs": paras}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--src")
    parser.add_argument("--index", type=int, default=1)
    args = parser.parse_args()
    if args.src:
        payload = json.loads(Path(args.src).read_text(encoding="utf-8"))
    else:
        payload = json.loads(sys.stdin.read())
    dest_dir = STAGING / args.ticker.strip().upper() / args.period.strip().upper()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{args.index:03d}.json"
    dest.write_text(json.dumps(slim(payload), ensure_ascii=False), encoding="utf-8")
    print(f"WROTE={dest} PARAS={len(slim(payload)['paragraphs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
