"""Finish remaining DDOG LLM stages. Writes after each dimension quarter."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
PY = sys.executable

DIMS_LEFT: list[str] = []
LATER = [
    "FY2019-Q4",
    "FY2020-Q1",
    "FY2020-Q2",
    "FY2020-Q3",
    "FY2020-Q4",
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
    "FY2024-Q4",
    "FY2025-Q1",
    "FY2025-Q2",
]


def run(args: list[str]) -> None:
    print("+", " ".join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> int:
    dim = SN / "run_dimension_scoring.py"
    uni = SN / "run_universe_batch.py"
    for fp in DIMS_LEFT:
        run([str(PY), "-u", str(dim), "--ticker", "DDOG", "--quarters", fp])
    run(
        [
            str(PY),
            "-u",
            str(uni),
            "--tickers",
            "DDOG",
            "--stages",
            "delta",
            "surprise",
            "novelty",
            "--quarters",
            *LATER,
        ]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
