#!/usr/bin/env python3
"""Assemble staged Quartr MCP transcript windows into transcripts_raw.

Staging layout:
  data/healthcare_large_cap/windows/{TICKER}/{PERIOD}/000.json
  data/healthcare_large_cap/windows/{TICKER}/{PERIOD}/001.json

Each JSON is a raw read_transcript payload. Files are concatenated in name order.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
STAGING = REPO / "data" / "healthcare_large_cap" / "windows"
OUT = REPO / "Structured Narrative" / "transcripts_raw"


def paragraphs_to_text(paragraphs: list[object]) -> str:
    chunks: list[str] = []
    last_speaker = ""
    for item in paragraphs:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        speaker = str(item.get("speakerName") or item.get("speaker") or "").strip()
        if speaker and speaker != last_speaker:
            chunks.append(f"{speaker}:")
            last_speaker = speaker
        chunks.append(text)
    return "\n".join(chunks).strip()


def assemble_period(ticker: str, period: str, folder: Path) -> Path | None:
    windows = sorted(p for p in folder.glob("*.json") if p.is_file())
    if not windows:
        return None
    texts: list[str] = []
    for path in windows:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        text = paragraphs_to_text(payload.get("paragraphs") or [])
        if text:
            texts.append(text)
    if not texts:
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    dest = OUT / f"{ticker}_{period}.txt"
    dest.write_text("\n".join(texts) + "\n", encoding="utf-8")
    return dest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", action="append", default=[])
    args = parser.parse_args()
    wanted = {t.strip().upper() for t in args.ticker if t.strip()}
    written = 0
    if not STAGING.is_dir():
        print("NO_STAGING")
        return 1
    for ticker_dir in sorted(p for p in STAGING.iterdir() if p.is_dir()):
        ticker = ticker_dir.name.upper()
        if wanted and ticker not in wanted:
            continue
        for period_dir in sorted(p for p in ticker_dir.iterdir() if p.is_dir()):
            dest = assemble_period(ticker, period_dir.name.upper(), period_dir)
            if dest:
                print(dest)
                written += 1
    print(f"WROTE={written}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
