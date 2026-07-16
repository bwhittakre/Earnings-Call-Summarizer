#!/usr/bin/env python3
"""Backfill incomplete registry quarters (with transcripts) and rebuild outputs."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PY = sys.executable
TICKERS = ("MSFT", "NVDA", "AMZN", "AAPL")
RAW = HERE / "transcripts_raw"


def transcript_available(ticker: str, fiscal_period: str) -> bool:
    if (RAW / f"{ticker}_{fiscal_period}.txt").is_file():
        return True
    return (HERE / ticker / f"{fiscal_period}.txt").is_file()


def incomplete_with_transcripts(ticker: str) -> list[str]:
    from company_config import get_company
    from quarter_registry import is_quarter_complete, load_registry

    company = get_company(ticker)
    reg = load_registry(ticker)
    prior = set(reg.get("prior_only_quarters", []))
    out: list[str] = []
    for fp in company.output_quarters:
        if fp in prior:
            continue
        if is_quarter_complete(reg, fp):
            continue
        if transcript_available(ticker, fp):
            out.append(fp)
    return out


def main() -> int:
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))

    rc = 0
    for ticker in TICKERS:
        gaps = incomplete_with_transcripts(ticker)
        print(f"\n{'=' * 60}")
        print(f"{ticker}: {len(gaps)} incomplete quarter(s) with transcripts")
        if gaps:
            print(f"  {', '.join(gaps)}")
        print("=" * 60)
        if not gaps:
            continue

        subprocess.run(
            [PY, str(HERE / "export_inbox_to_transcripts_raw.py"), "--ticker", ticker],
            cwd=REPO,
            check=False,
        )
        cmd = [
            PY,
            str(HERE / "run_company_pipeline.py"),
            "--ticker", ticker,
            "--skip-quant",
            "--quarters", *gaps,
        ]
        result = subprocess.run(cmd, cwd=REPO)
        if result.returncode != 0:
            print(f"FAIL {ticker} exit={result.returncode}", file=sys.stderr)
            rc = result.returncode

    print("\n=== Consolidated cross-section report ===")
    report_cmd = [
        PY,
        str(HERE / "build_consolidated_panel_report.py"),
        "--tickers", *TICKERS,
        "--scope", "fy2025_26",
        "--output-stem", "cross_section_panel",
        "--quarter", "FY2025-Q4",
    ]
    result = subprocess.run(report_cmd, cwd=REPO)
    if result.returncode != 0:
        rc = result.returncode
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
