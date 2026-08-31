#!/usr/bin/env python3
"""Write a slim continuation window from a JSON payload on stdin or --src."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"


def slim_paragraphs(paragraphs: list[object]) -> list[dict]:
    out: list[dict] = []
    for item in paragraphs:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        speaker = str(item.get("speakerName") or item.get("speaker") or "").strip()
        row: dict = {"text": text}
        if speaker:
            row["speakerName"] = speaker
        start = item.get("start")
        if start is not None:
            row["start"] = start
        out.append(row)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--window", required=True, type=int)
    args = parser.parse_args()
    raw = Path(args.src).read_text(encoding="utf-8") if args.src else sys.stdin.read()
    data = json.loads(raw)
    payload = {
        "eventId": data.get("eventId"),
        "isLive": bool(data.get("isLive")),
        "nextFromTimestamp": data.get("nextFromTimestamp"),
        "paragraphs": slim_paragraphs(data.get("paragraphs") or []),
    }
    dest_dir = STAGING / args.ticker.upper() / args.period.upper()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{args.window:03d}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"WROTE={dest} paras={len(payload['paragraphs'])} next={payload['nextFromTimestamp']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
