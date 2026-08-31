#!/usr/bin/env python3
"""Persist page-2 windows from agent-tools by matching 000.json nextFromTimestamp."""
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
    parser.add_argument("--tools", default=str(DEFAULT_TOOLS))
    args = parser.parse_args()
    ticker = args.ticker.strip().upper()
    root = STAGING / ticker
    wanted: dict[int, tuple[str, float]] = {}
    for period_dir in sorted(root.iterdir()) if root.exists() else []:
        page1 = period_dir / "000.json"
        page2 = period_dir / "001.json"
        if not page1.exists() or page2.exists():
            continue
        body = json.loads(page1.read_text(encoding="utf-8"))
        nxt = body.get("nextFromTimestamp")
        if nxt is None:
            continue
        wanted[int(body["eventId"])] = (period_dir.name, float(nxt))
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
        if first is None:
            continue
        expect = wanted[eid][1]
        if abs(float(first) - expect) > 1.0:
            continue
        mtime = src.stat().st_mtime
        prev = best.get(eid)
        if prev is None or mtime > prev[0]:
            best[eid] = (mtime, src, payload)
    wrote = 0
    missing = []
    for eid, (period, expect) in wanted.items():
        if eid not in best:
            missing.append((eid, period, expect))
            continue
        _, src, payload = best[eid]
        dest = root / period / "001.json"
        body = slim(payload)
        dest.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        print(f"WROTE={dest} EVENT={eid} PARAS={len(body['paragraphs'])} SRC={src.name}")
        wrote += 1
    for eid, period, expect in missing:
        print(f"MISSING={eid} PERIOD={period} FROM={expect}")
    print(f"WROTE_COUNT={wrote} MISSING_COUNT={len(missing)} WANTED={len(wanted)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
