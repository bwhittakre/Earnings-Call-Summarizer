#!/usr/bin/env python3
"""Copy a Quartr read_transcript dump into healthcare staging.

Usage:
  python scripts/_stage_quartr_window.py --ticker TMO --period FY2016-Q1 --src path.json
  python scripts/_stage_quartr_window.py --ticker TMO --period FY2016-Q1 --src path.json --index 1
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--src", required=True, type=Path)
    parser.add_argument("--index", type=int, default=None)
    args = parser.parse_args()

    payload = json.loads(args.src.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"not an object: {args.src}")

    dest_dir = STAGING / args.ticker.strip().upper() / args.period.strip().upper()
    dest_dir.mkdir(parents=True, exist_ok=True)
    index = args.index
    if index is None:
        existing = sorted(dest_dir.glob("*.json"))
        index = len(existing)
    dest = dest_dir / f"{index:03d}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    nxt = payload.get("nextFromTimestamp")
    npar = len(payload.get("paragraphs") or [])
    print(f"{dest} event={payload.get('eventId')} npar={npar} next={nxt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
