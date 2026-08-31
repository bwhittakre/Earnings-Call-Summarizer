#!/usr/bin/env python3
"""Ingest recent agent-tools transcript dumps into wave C staging windows."""
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
    if isinstance(data, dict) and "paragraphs" in data and "eventId" in data:
        return data
    if isinstance(data, dict) and isinstance(data.get("result"), dict):
        inner = data["result"]
        if "paragraphs" in inner and "eventId" in inner:
            return inner
    return None


def slim(payload: dict) -> dict:
    paras = []
    for p in payload.get("paragraphs") or []:
        paras.append({"speakerName": p.get("speakerName") or "", "text": p.get("text") or ""})
    return {"eventId": payload["eventId"], "isLive": False, "paragraphs": paras}


def index_windows(ticker: str) -> dict[int, tuple[str, Path]]:
    found: dict[int, tuple[str, Path]] = {}
    root = STAGING / ticker
    if not root.is_dir():
        return found
    for period_dir in root.iterdir():
        z = period_dir / "000.json"
        if not z.exists():
            continue
        try:
            payload = json.loads(z.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        eid = payload.get("eventId")
        if eid is not None:
            found[int(eid)] = (period_dir.name, period_dir)
    return found


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--tools", default=str(DEFAULT_TOOLS))
    parser.add_argument("--index", type=int, default=1)
    parser.add_argument("--newer-than", type=float, default=0)
    args = parser.parse_args()
    ticker = args.ticker.strip().upper()
    tools = Path(args.tools)
    windows = index_windows(ticker)
    wrote = 0
    skipped = 0
    for src in sorted(tools.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True):
        if args.newer_than and src.stat().st_mtime < args.newer_than:
            continue
        payload = load_payload(src.read_text(encoding="utf-8"))
        if not payload:
            continue
        eid = int(payload["eventId"])
        if eid not in windows:
            continue
        period, dest_dir = windows[eid]
        dest = dest_dir / f"{args.index:03d}.json"
        if dest.exists() and dest.stat().st_size > 200:
            skipped += 1
            continue
        zero = dest_dir / "000.json"
        if args.index > 0 and zero.exists():
            try:
                zpay = json.loads(zero.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                zpay = {}
            nxt = zpay.get("nextFromTimestamp")
            first = None
            paras = payload.get("paragraphs") or []
            if paras and isinstance(paras[0], dict):
                first = paras[0].get("start")
            # Skip page-1 dumps being written as later windows.
            if nxt in (None, "", 0):
                skipped += 1
                continue
            if first is not None and float(first) + 1e-6 < float(nxt):
                skipped += 1
                continue
        dest.write_text(json.dumps(slim(payload), ensure_ascii=False), encoding="utf-8")
        nxt = payload.get("nextFromTimestamp")
        print(f"WROTE={dest} EVENT={eid} PARAS={len(slim(payload)['paragraphs'])} NEXT_FROM={nxt} SRC={src.name}")
        wrote += 1
    print(f"WROTE_COUNT={wrote} SKIPPED={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
