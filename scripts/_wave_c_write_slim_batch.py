#!/usr/bin/env python3
"""Write slim 001.json files from a JSON list of {period, eventId, paragraphs}."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"


def slim_paras(paragraphs: list) -> list[dict]:
    out = []
    for p in paragraphs or []:
        out.append({"speakerName": p.get("speakerName") or "", "text": p.get("text") or ""})
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--src", required=True)
    parser.add_argument("--index", type=int, default=1)
    args = parser.parse_args()
    items = json.loads(Path(args.src).read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = [{"period": k, **v} for k, v in items.items()]
    ticker = args.ticker.strip().upper()
    wrote = 0
    for item in items:
        period = item["period"]
        dest_dir = STAGING / ticker / period
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{args.index:03d}.json"
        paras = slim_paras(item.get("paragraphs") or [])
        dest.write_text(
            json.dumps(
                {"eventId": item["eventId"], "isLive": False, "paragraphs": paras},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"WROTE={dest} EVENT={item['eventId']} PARAS={len(paras)}")
        wrote += 1
    print(f"COUNT={wrote}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
