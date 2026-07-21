#!/usr/bin/env python3
"""Score local historical transcripts for AAPL / MSFT; refresh AMZN panel.

NVDA intentionally omitted until transcripts are ready.
Snowflake quant extract is skipped (network policy); cached spines are reused.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
PY = sys.executable

JOBS: dict[str, list[str]] = {
    "MSFT": [
        "FY2021-Q4",
        "FY2022-Q1",
        "FY2022-Q2",
        "FY2022-Q3",
        "FY2022-Q4",
        "FY2023-Q1",
        "FY2023-Q2",
        "FY2023-Q3",
        "FY2023-Q4",
        "FY2024-Q1",
        "FY2024-Q2",
        "FY2024-Q3",
    ],
    "AAPL": [
        "FY2021-Q3",
        "FY2021-Q4",
        "FY2022-Q1",
        "FY2022-Q2",
        "FY2022-Q3",
        "FY2022-Q4",
        "FY2023-Q1",
        "FY2023-Q2",
        "FY2023-Q3",
        "FY2023-Q4",
        "FY2024-Q1",
        "FY2024-Q2",
        "FY2024-Q3",
    ],
    "NVDA": [
        "FY2022-Q2",
        "FY2022-Q3",
        "FY2022-Q4",
        "FY2023-Q1",
        "FY2023-Q2",
        "FY2023-Q3",
        "FY2023-Q4",
        "FY2024-Q1",
        "FY2024-Q2",
        "FY2024-Q3",
    ],
}


def run(cmd: list[str]) -> int:
    print("\n>>>", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=REPO).returncode


def main() -> int:
    tickers = [a.upper() for a in sys.argv[1:]] or ["MSFT", "AAPL", "AMZN"]
    rc = 0

    for ticker in tickers:
        print(f"\n{'=' * 70}\nBACKFILL {ticker}\n{'=' * 70}", flush=True)

        if ticker == "AMZN":
            code = run(
                [
                    PY,
                    str(HERE / "run_dimension_scoring.py"),
                    "--ticker",
                    "AMZN",
                    "--quarters",
                    "FY2019-Q2",
                ]
            )
            if code != 0:
                rc = code
            code = run(
                [
                    PY,
                    str(HERE / "run_company_pipeline.py"),
                    "--ticker",
                    "AMZN",
                    "--skip-quant",
                    "--skip-llm",
                    "--from-registry",
                ]
            )
            if code != 0:
                rc = code
            continue

        qs = JOBS.get(ticker)
        if not qs:
            print(f"SKIP unknown ticker {ticker}", file=sys.stderr)
            continue

        code = run(
            [
                PY,
                str(HERE / "run_company_pipeline.py"),
                "--ticker",
                ticker,
                "--skip-quant",
                "--quarters",
                *qs,
                "--from-registry",
            ]
        )
        if code != 0:
            print(f"FAIL {ticker} exit={code}", file=sys.stderr)
            rc = code

    print(f"\nBackfill finished with exit={rc}", flush=True)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
