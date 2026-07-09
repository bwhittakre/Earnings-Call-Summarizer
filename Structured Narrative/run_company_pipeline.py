#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run the full Structured Narrative pipeline for one ticker.

    python "Structured Narrative/run_company_pipeline.py" --ticker AMZN
    python "Structured Narrative/run_company_pipeline.py" --ticker MSFT --skip-llm
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from output_paths import ensure_company_tree  # noqa: E402


def run_step(label: str, cmd: list[str]) -> None:
    print(f"\n=== {label} ===")
    print(" ".join(cmd))
    env = os.environ.copy()
    env.setdefault("TRANSCRIPT_PROVIDER", "local")
    subprocess.run(cmd, cwd=HERE.parent, check=True, env=env)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run quant + LLM pipeline for one ticker.")
    ap.add_argument("--ticker", required=True, help="Ticker symbol.")
    ap.add_argument("--skip-quant", action="store_true", help="Skip Snowflake quant spine.")
    ap.add_argument("--skip-llm", action="store_true", help="Skip LLM scoring steps.")
    ap.add_argument(
        "--quarters",
        nargs="+",
        default=[],
        help="Re-score only these fiscal periods (e.g. FY2025-Q1 FY2025-Q2).",
    )
    args = ap.parse_args()
    ticker = args.ticker.upper()
    sn = str(HERE)
    quarter_args = ["--quarters", *args.quarters] if args.quarters else []
    ensure_company_tree(ticker)
    print(f"Output tree ready: output/{ticker}/{{parquet,workbooks,csv,json,reports,audit}}")

    if not args.skip_quant:
        run_step("Quant extract", [PY, f"{sn}/single_company_extractor.py", "--ticker", ticker])
        run_step("Quant z-score", [PY, f"{sn}/narrative_zscore.py", "--ticker", ticker])

    if not args.skip_llm:
        run_step(
            "Bridge inbox transcripts",
            [PY, f"{sn}/export_inbox_to_transcripts_raw.py", "--ticker", ticker],
        )
        run_step("Focus 1 dimensions", [PY, f"{sn}/run_dimension_scoring.py", "--ticker", ticker, *quarter_args])
        run_step("Focus 2 delta", [PY, f"{sn}/run_delta_scoring.py", "--ticker", ticker, *quarter_args])
        run_step("Focus 3 surprise", [PY, f"{sn}/run_surprise_scoring.py", "--ticker", ticker, *quarter_args])

    run_step("Feature panel", [PY, f"{sn}/build_feature_panel.py", "--ticker", ticker])

    run_step("Join validation", [PY, f"{sn}/validate_transcript_join.py", "--ticker", ticker])
    print(f"\nDone: {ticker} pipeline complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
