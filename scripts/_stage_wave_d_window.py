#!/usr/bin/env python3
"""Stage a Quartr read_transcript dump for healthcare wave D. Do not reuse for other waves."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"


def load_payload(path: Path) -> dict:
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if isinstance(data, dict) and "paragraphs" in data:
        return data
    if isinstance(data, dict) and "result" in data and isinstance(data["result"], dict):
        return data["result"]
    if isinstance(data, dict) and "structuredContent" in data:
        inner = data["structuredContent"]
        if isinstance(inner, dict) and "paragraphs" in inner:
            return inner
    raise SystemExit(f"Unrecognized transcript payload: {path}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--index", required=True, type=int)
    parser.add_argument("--src", required=True, type=Path)
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()
    period = args.period.strip().upper()
    payload = load_payload(args.src)
    dest_dir = STAGING / ticker / period
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{args.index:03d}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    paras = payload.get("paragraphs") or []
    nxt = payload.get("nextFromTimestamp")
    print(dest)
    print(f"PARAS={len(paras)}")
    print(f"NEXT_FROM={'' if nxt is None else nxt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
