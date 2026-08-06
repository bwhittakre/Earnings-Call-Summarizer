#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Offline call / tape reaction scaffold.

Joins Bloomberg 1-minute bars to Quartr timed transcript paragraphs and writes
typed artifacts under Live Ticker Reaction/Output/{Reports|Tables|Diagnostics}/.

    python "Structured Narrative/run_ticker_reaction.py"
    python "Structured Narrative/run_ticker_reaction.py" --ticker AMZN --quarter FY2026-Q2
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from ticker_reaction.pipeline import run_ticker_reaction  # noqa: E402

DESKTOP_LTR = Path(
    r"C:\Users\BobbyWhittaker\OneDrive - Cassius Capital\Desktop"
    r"\Earnings Call Summarizer\Live Ticker Reaction"
)


def default_data_dir() -> Path:
    repo_ltr = REPO_ROOT / "Live Ticker Reaction"
    anchors_name = "AMZN_FY2026-Q2_event_anchors.json"
    if (repo_ltr / anchors_name).exists():
        return repo_ltr
    if (DESKTOP_LTR / anchors_name).exists():
        return DESKTOP_LTR
    return repo_ltr


def main() -> int:
    data_default = default_data_dir()
    ap = argparse.ArgumentParser(description="Offline ticker reaction smoke join.")
    ap.add_argument("--ticker", default="AMZN")
    ap.add_argument("--quarter", default="FY2026-Q2")
    ap.add_argument(
        "--data-dir",
        type=Path,
        default=data_default,
        help="Folder containing bars Excel + timed transcript + anchors JSON.",
    )
    ap.add_argument(
        "--bars",
        type=Path,
        default=None,
        help="Override bars Excel path.",
    )
    ap.add_argument(
        "--transcript",
        type=Path,
        default=None,
        help="Override timed transcript JSON path.",
    )
    ap.add_argument(
        "--anchors",
        type=Path,
        default=None,
        help="Override event anchors JSON path.",
    )
    ap.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Base Output folder (default: <data-dir>/Output).",
    )
    args = ap.parse_args()

    data_dir = args.data_dir
    ticker = args.ticker.upper()
    quarter = args.quarter.upper()
    slug = f"{ticker}_{quarter}"

    bars = args.bars or (data_dir / "AMZN 2026-Q2 Live Test beta.xlsx")
    # Prefer ticker-specific names when present; fall back to AMZN pilot filenames.
    if args.bars is None:
        candidates = list(data_dir.glob(f"{ticker}*.xlsx")) + list(data_dir.glob("*.xlsx"))
        if candidates:
            # Prefer filename containing ticker and quarter tokens when possible.
            ranked = sorted(
                candidates,
                key=lambda p: (
                    0 if ticker.lower() in p.name.lower() else 1,
                    0 if "q2" in p.name.lower() or "2026" in p.name else 1,
                    p.name,
                ),
            )
            bars = ranked[0]

    transcript = args.transcript or (data_dir / f"{slug}_quartr_timed_transcript.json")
    anchors = args.anchors or (data_dir / f"{slug}_event_anchors.json")
    output_root = args.output_root or (data_dir / "Output")

    for label, path in (
        ("bars", bars),
        ("transcript", transcript),
        ("anchors", anchors),
    ):
        if not Path(path).exists():
            print(f"ERROR: missing {label} file: {path}", file=sys.stderr)
            return 2

    result = run_ticker_reaction(
        bars_path=Path(bars),
        transcript_path=Path(transcript),
        anchors_path=Path(anchors),
        output_root=Path(output_root),
        ticker=ticker,
        quarter=quarter,
    )

    report_path = result["paths"]["report"]
    print("=== Ticker Reaction complete ===")
    print(f"Event:     {result['slug']}")
    print(f"REPORT:    {report_path}")
    print(f"Table:     {result['paths']['table']}")
    print(f"Diagnostics: {result['paths']['diagnostics']}")
    diag = result["diagnostics"]
    print(
        f"Match: {diag.get('matched_count')}/{diag.get('paragraph_count')} "
        f"({(100.0 * (diag.get('match_rate') or 0)):.1f}%)"
    )
    print(json.dumps({"summary_returns": {
        "report_to_call": diag.get("cum_return_report_to_call"),
        "call_to_end": diag.get("cum_return_call_to_end"),
    }}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
