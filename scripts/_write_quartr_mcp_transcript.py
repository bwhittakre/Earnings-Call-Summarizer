#!/usr/bin/env python3
"""Write a Quartr MCP read_transcript payload to LocalFileProvider layout.

Usage:
  python scripts/_write_quartr_mcp_transcript.py --ticker LLY --period FY2026-Q2 \\
      --payload path/to/window.json [--append]

Speaker labels are written as ``Name:`` so LocalFileProvider can split QA.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO / "Structured Narrative" / "transcripts_raw"


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


def load_payload(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Payload is not an object: {path}")
    return data


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--period", required=True)
    parser.add_argument("--payload", required=True, type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--append", action="store_true")
    args = parser.parse_args()

    ticker = args.ticker.strip().upper()
    period = args.period.strip().upper()
    payload = load_payload(args.payload)
    text = paragraphs_to_text(payload.get("paragraphs") or [])
    if not text:
        raise SystemExit(f"No paragraph text in {args.payload}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    dest = args.out_dir / f"{ticker}_{period}.txt"
    if args.append and dest.is_file():
        existing = dest.read_text(encoding="utf-8").rstrip()
        dest.write_text(existing + "\n" + text + "\n", encoding="utf-8")
    else:
        dest.write_text(text + "\n", encoding="utf-8")
    print(dest)
    nxt = payload.get("nextFromTimestamp")
    if nxt is not None:
        print(f"NEXT_FROM={nxt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
