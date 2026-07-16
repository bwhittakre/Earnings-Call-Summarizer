#!/usr/bin/env python3
"""
Batch pipeline for pilot tickers on the last N ROIC.ai earnings-call quarters.

"Last 8 quarters" means the 8 most recent calls available from ROIC.ai
(``fetch_transcripts.py --last 8``), not a fixed calendar FY2025–FY2026 window.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
SN = HERE
PY = sys.executable

TICKERS = ("MSFT", "NVDA", "AMZN", "AAPL")
LAST_N = 8


def main() -> int:
    if str(SN) not in sys.path:
        sys.path.insert(0, str(SN))
    from roic_quarters import (
        bridge_inbox,
        fetch_roic_transcripts,
        resolve_scoring_quarters,
        write_quarter_manifest,
    )

    print(f"=== Fetch last {LAST_N} quarters from ROIC.ai ===")
    fetch_roic_transcripts(list(TICKERS), last_n=LAST_N)

    print("\n=== Bridge inbox -> transcripts_raw ===")
    bridge_inbox(list(TICKERS))

    from fiscal_period_util import fiscal_period_sort_key

    by_ticker = write_quarter_manifest(list(TICKERS), last_n=LAST_N)
    union = sorted({q for qs in by_ticker.values() for q in qs}, key=fiscal_period_sort_key)

    rc = 0
    for ticker in TICKERS:
        qs = resolve_scoring_quarters(ticker, last_n=LAST_N)
        if not qs:
            print(f"SKIP {ticker}: no ROIC/local transcripts for last {LAST_N}", file=sys.stderr)
            continue
        print(f"\n{'=' * 60}\n{ticker}: {len(qs)} quarter(s) — {', '.join(qs)}\n{'=' * 60}")
        cmd = [
            PY,
            str(SN / "run_company_pipeline.py"),
            "--ticker", ticker,
            "--skip-quant",
            "--force",
            "--quarters", *qs,
        ]
        result = subprocess.run(cmd, cwd=REPO)
        if result.returncode != 0:
            print(f"FAIL {ticker} exit={result.returncode}", file=sys.stderr)
            rc = result.returncode

    print("\n=== Consolidated cross-section report ===")
    report_cmd = [
        PY,
        str(SN / "build_consolidated_panel_report.py"),
        "--tickers", *TICKERS,
        "--quarters", *union,
        "--output-stem", "cross_section_panel",
    ]
    if union:
        report_cmd.extend(["--quarter", union[-1]])
    result = subprocess.run(report_cmd, cwd=REPO)
    if result.returncode != 0:
        rc = result.returncode
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
