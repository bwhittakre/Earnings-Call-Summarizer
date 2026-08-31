#!/usr/bin/env python3
"""Persist page-1 windows (000.json) from agent-tools by eventId."""
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
    return {
        "eventId": payload["eventId"],
        "isLive": False,
        "nextFromTimestamp": payload.get("nextFromTimestamp"),
        "paragraphs": paras,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--map", required=True, help="JSON {eventId: period}")
    parser.add_argument("--tools", default=str(DEFAULT_TOOLS))
    parser.add_argument("--index", type=int, default=0)
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
        if first is None or float(first) > 30:
            continue
        mtime = src.stat().st_mtime
        prev = best.get(eid)
        if prev is None or mtime > prev[0]:
            best[eid] = (mtime, src, payload)
    wrote = 0
    missing = []
    for eid, period in wanted.items():
        if eid not in best:
            missing.append((eid, period))
            continue
        _, src, payload = best[eid]
        dest_dir = STAGING / ticker / period
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{args.index:03d}.json"
        body = slim(payload)
        dest.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        print(
            f"WROTE={dest} EVENT={eid} PARAS={len(body['paragraphs'])} "
            f"NEXT={body['nextFromTimestamp']} SRC={src.name}"
        )
        wrote += 1
    for eid, period in missing:
        print(f"MISSING={eid} PERIOD={period}")
    print(f"WROTE_COUNT={wrote} MISSING_COUNT={len(missing)} WANTED={len(wanted)}")
    return 0 if not missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
