#!/usr/bin/env python3
"""Write slim page-2 windows from a JSON map of period -> {eventId, paragraphs}."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--src", required=True)
    parser.add_argument("--index", type=int, default=1)
    args = parser.parse_args()
    blob = json.loads(Path(args.src).read_text(encoding="utf-8"))
    ticker = args.ticker.strip().upper()
    wrote = 0
    for period, payload in blob.items():
        dest_dir = STAGING / ticker / period
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{args.index:03d}.json"
        paras = []
        for p in payload.get("paragraphs") or []:
            paras.append({"speakerName": p.get("speakerName") or "", "text": p.get("text") or ""})
        dest.write_text(
            json.dumps(
                {"eventId": payload["eventId"], "isLive": False, "paragraphs": paras},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"WROTE={dest} PARAS={len(paras)}")
        wrote += 1
    print(f"COUNT={wrote}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
