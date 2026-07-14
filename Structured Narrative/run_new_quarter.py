#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-end workflow for one new earnings quarter.

Steps:
  1. (optional) Bridge inbox transcripts -> transcripts_raw/
  2. (optional) Append quant spine quarters + z-score + refresh anchors
  3. Score new quarter (Focus 1/2/3) via run_company_pipeline
  4. Export cross-company modeling spine

    python "Structured Narrative/run_new_quarter.py" --ticker MSFT --quarter FY2026-Q4
    python "Structured Narrative/run_new_quarter.py" --ticker NVDA --quarter FY2026-Q2 --skip-quant
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
PY = sys.executable
SN = str(HERE)

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from company_config import PILOT_TICKERS  # noqa: E402
from fiscal_period_util import normalize_fiscal_period  # noqa: E402


def run(cmd: list[str], *, label: str) -> None:
    print(f"\n=== {label} ===")
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=REPO_ROOT, check=True, env=os.environ.copy())


def main() -> int:
    ap = argparse.ArgumentParser(description="New-quarter workflow wrapper.")
    ap.add_argument("--ticker", required=True)
    ap.add_argument("--quarter", required=True, metavar="FYyyyy-Qn")
    ap.add_argument("--skip-bridge", action="store_true", help="Skip inbox -> transcripts_raw bridge.")
    ap.add_argument("--skip-quant", action="store_true", help="Skip Snowflake quant append/z-score.")
    ap.add_argument("--skip-spine", action="store_true", help="Skip cross-company modeling spine export.")
    ap.add_argument("--force", action="store_true", help="Re-score even if registry marks quarter complete.")
    ap.add_argument(
        "--spine-tickers",
        nargs="+",
        default=list(PILOT_TICKERS),
        help="Tickers to include in modeling spine export.",
    )
    args = ap.parse_args()
    ticker = args.ticker.upper()
    quarter = normalize_fiscal_period(args.quarter)

    if not args.skip_bridge:
        run(
            [PY, f"{SN}/export_inbox_to_transcripts_raw.py", "--ticker", ticker],
            label="Bridge inbox transcripts",
        )

    pipeline_cmd = [
        PY,
        f"{SN}/run_company_pipeline.py",
        "--ticker",
        ticker,
        "--new-quarter",
        quarter,
    ]
    if args.skip_quant:
        pipeline_cmd.append("--skip-quant")
    if args.force:
        pipeline_cmd.append("--force")
    if not args.skip_quant:
        pipeline_cmd.extend(["--append-quarters", quarter])

    run(pipeline_cmd, label="Company pipeline")

    if not args.skip_spine:
        spine_tickers = [t.upper() for t in args.spine_tickers]
        run(
            [
                PY,
                f"{SN}/export_modeling_spine.py",
                "--tickers",
                *spine_tickers,
                "--include-labels",
            ],
            label="Export modeling spine",
        )
        run(
            [PY, f"{SN}/evaluate_narrative_signals.py", "--tickers", *spine_tickers],
            label="Evaluate narrative signals",
        )

    print(f"\nDone: {ticker} {quarter} workflow complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
