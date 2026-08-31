#!/usr/bin/env python3
"""Slim a raw Quartr transcript JSON file into a staging window."""
from __future__ import annotations

import argparse
import json
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
    parser.add_argument("--src", required=True)
    parser.add_argument("--index", type=int, default=1)
    args = parser.parse_args()
    payload = json.loads(Path(args.src).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        payload = payload["result"]
    dest_dir = STAGING / args.ticker.strip().upper() / args.period.strip().upper()
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{args.index:03d}.json"
    body = slim(payload)
    dest.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    print(f"WROTE={dest} EVENT={body['eventId']} PARAS={len(body['paragraphs'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
