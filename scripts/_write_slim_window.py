#!/usr/bin/env python3
"""Write a slim persist-ready window JSON from a paragraphs JSONL file."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TMP = REPO / "data" / "healthcare_large_cap" / "windows" / "_tmp"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", required=True, type=int)
    parser.add_argument("--period", required=True)
    parser.add_argument("--paras", required=True)
    args = parser.parse_args()
    paras = []
    for line in Path(args.paras).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        item = {"text": str(row["text"]).strip()}
        speaker = str(row.get("speakerName") or "").strip()
        if speaker:
            item["speakerName"] = speaker
        if row.get("start") is not None:
            item["start"] = row["start"]
        if item["text"]:
            paras.append(item)
    TMP.mkdir(parents=True, exist_ok=True)
    dest = TMP / f"JNJ_{args.period}.json"
    payload = {
        "eventId": args.event_id,
        "isLive": False,
        "nextFromTimestamp": None,
        "paragraphs": paras,
    }
    dest.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    print(f"WROTE={dest} paras={len(paras)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
