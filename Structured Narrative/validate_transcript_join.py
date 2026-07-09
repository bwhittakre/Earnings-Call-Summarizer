#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validate quant spine fiscal_period labels align with local transcripts.

    python "Structured Narrative/validate_transcript_join.py"
    python "Structured Narrative/validate_transcript_join.py" --ticker MSFT
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"
TRANSCRIPTS_DIR = HERE / "transcripts_raw"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from company_config import PILOT_TICKERS, get_company  # noqa: E402
from transcript_providers import LocalFileProvider, TranscriptNotFound  # noqa: E402


def transcript_path(ticker: str, fiscal_period: str) -> Path | None:
    provider = LocalFileProvider()
    for candidate in provider._candidates(ticker, fiscal_period):
        if candidate.exists():
            return candidate
    return None


def validate_ticker(ticker: str) -> int:
    company = get_company(ticker)
    dim_file = OUT_DIR / f"{ticker}_dimension_scores.csv"
    issues = 0

    print(f"\n{ticker} ({company.company_name})")
    print("-" * 60)

    if dim_file.exists():
        quant = pd.read_csv(dim_file)
        quant_periods = sorted(quant["fiscal_period"].unique())
    else:
        quant_periods = []
        print(f"  ! missing quant spine: {dim_file.name}")

    scoring = company.scoring_quarters()
    print(f"  Scoring quarters: {', '.join(scoring)}")

    for fp in scoring:
        qrow = None
        if quant_periods:
            qrow = quant[quant["fiscal_period"] == fp]
        tpath = transcript_path(ticker, fp)
        has_quant = not qrow.empty if qrow is not None else False
        has_tx = tpath is not None

        status_parts = []
        if has_quant:
            ed = qrow.iloc[0].get("earnings_date", "n/a")
            status_parts.append(f"quant earnings_date={ed}")
        else:
            status_parts.append("NO quant row")
            issues += 1
        if has_tx:
            status_parts.append(f"transcript={tpath.name}")
        else:
            status_parts.append("NO transcript")
            issues += 1

        if has_tx:
            try:
                LocalFileProvider().fetch(ticker, fp)
                status_parts.append("load=OK")
            except TranscriptNotFound as exc:
                status_parts.append(f"load=FAIL ({exc})")
                issues += 1

        print(f"  {fp}: {' | '.join(status_parts)}")

    if quant_periods:
        extra_quant = [p for p in quant_periods if p in scoring]
        print(f"  Quant spine rows in scope: {len(extra_quant)}/{len(scoring)}")

    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate quant/transcript fiscal_period alignment.")
    ap.add_argument("--ticker", action="append", default=[], help="Ticker(s) to check.")
    args = ap.parse_args()
    tickers = [t.upper() for t in args.ticker] or list(PILOT_TICKERS)

    total_issues = 0
    for ticker in tickers:
        total_issues += validate_ticker(ticker)

    print(f"\nDone: {total_issues} issue(s) across {len(tickers)} ticker(s).")
    return 1 if total_issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
