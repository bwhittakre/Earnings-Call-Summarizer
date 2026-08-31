#!/usr/bin/env python3
"""Wave C only: stage a Quartr read_transcript dump and report pagination."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"


def load_payload(text: str) -> dict:
    data = json.loads(text)
    if isinstance(data, dict) and "paragraphs" in data:
        return data
    if isinstance(data, dict) and isinstance(data.get("result"), dict) and "paragraphs" in data["result"]:
        return data["result"]
    if isinstance(data, dict) and isinstance(data.get("structuredContent"), dict):
        inner = data["structuredContent"]
        if "paragraphs" in inner:
            return inner
    raise SystemExit("Unrecognized transcript payload")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--src", required=True)
    parser.add_argument("--index", type=int, default=0)
    args = parser.parse_args()
    src = Path(args.src)
    payload = load_payload(src.read_text(encoding="utf-8"))
    dest_dir = STAGING / args.ticker.strip().upper() / args.period.strip().upper()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{args.index:03d}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    nxt = payload.get("nextFromTimestamp")
    n = len(payload.get("paragraphs") or [])
    print(f"WROTE={dest}")
    print(f"PARAS={n}")
    print(f"NEXT_FROM={nxt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
