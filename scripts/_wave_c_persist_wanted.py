#!/usr/bin/env python3
"""Persist wanted page-N windows from agent-tools dumps by eventId + first start."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"
DEFAULT_TOOLS = Path(
    r"C:\Users\BobbyWhittaker\.cursor\projects"
    r"\c-Users-BobbyWhittaker-OneDrive-Cassius-Capital-Desktop-Earnings-Call-Summarizer"
    r"\agent-tools"
)


def load_payload(text: str) -> dict | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        data = data["result"]
    if isinstance(data, dict) and "paragraphs" in data and "eventId" in data:
        return data
    return None


def slim(payload: dict) -> dict:
    paras = []
    for p in payload.get("paragraphs") or []:
        paras.append({"speakerName": p.get("speakerName") or "", "text": p.get("text") or ""})
    return {"eventId": payload["eventId"], "isLive": False, "paragraphs": paras}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--map", required=True, help="JSON {eventId: {period, fromTimestamp}}")
    parser.add_argument("--tools", default=str(DEFAULT_TOOLS))
    parser.add_argument("--index", type=int, default=1)
    args = parser.parse_args()
    ticker = args.ticker.strip().upper()
    wanted = {int(k): v for k, v in json.loads(Path(args.map).read_text(encoding="utf-8")).items()}
    tools = Path(args.tools)
    best: dict[int, tuple[float, Path, dict]] = {}
    for src in tools.glob("*.txt"):
        payload = load_payload(src.read_text(encoding="utf-8"))
        if not payload:
            continue
        eid = int(payload["eventId"])
        if eid not in wanted:
            continue
        paras = payload.get("paragraphs") or []
        first = paras[0].get("start") if paras and isinstance(paras[0], dict) else None
        expect = wanted[eid].get("fromTimestamp")
        if first is None or expect is None:
            continue
        if abs(float(first) - float(expect)) > 1.0:
            continue
        mtime = src.stat().st_mtime
        prev = best.get(eid)
        if prev is None or mtime > prev[0]:
            best[eid] = (mtime, src, payload)
    wrote = 0
    for eid, spec in wanted.items():
        period = spec["period"]
        if eid not in best:
            print(f"MISSING={eid} PERIOD={period}")
            continue
        _, src, payload = best[eid]
        dest_dir = STAGING / ticker / period
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{args.index:03d}.json"
        body = slim(payload)
        dest.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        print(f"WROTE={dest} EVENT={eid} PARAS={len(body['paragraphs'])} SRC={src.name}")
        wrote += 1
    print(f"WROTE_COUNT={wrote} WANTED={len(wanted)}")
    return 0 if wrote == len(wanted) else 2


if __name__ == "__main__":
    raise SystemExit(main())
