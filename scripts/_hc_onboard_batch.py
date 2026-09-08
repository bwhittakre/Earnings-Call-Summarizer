"""
HC Large Cap batch onboard — run tonight unattended.

Anchors each ticker at their latest scored period (FY2026-Q2 for 19 tickers,
FY2026-Q4 for MDT). Skips re-pulling data, quant scoring, and LLM scoring
since everything is already on disk.

What DOES run:
  - ID resolution (estpermid / isin / barra_id confirmed from overlay)
  - Quartr company_id written to overlay (via --quartr-company-id)
  - Fiscal calendar registered in config/fiscal_calendars.yaml
  - Ticker added to config/sectors/xlv_hc.txt
  - Ticker registered in monitor.sqlite3

Usage (from repo root, PowerShell):
    python scripts/_hc_onboard_batch.py [--dry-run]

The script runs onboards sequentially (one at a time) to avoid SQLite write
contention. Each run logs to stdout; failures are collected and reported at end.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# (ticker, period, report_at_iso, call_at_iso, quartr_company_id)
HC_TICKERS: list[tuple[str, str, str, str, int]] = [
    ("ABBV", "FY2026-Q2", "2026-07-31T13:00:00+00:00", "2026-07-31T13:00:00+00:00", 6137),
    ("ABT",  "FY2026-Q2", "2026-07-16T13:00:00+00:00", "2026-07-16T13:00:00+00:00", 4951),
    ("AMGN", "FY2026-Q2", "2026-08-04T20:30:00+00:00", "2026-08-04T20:30:00+00:00", 6430),
    ("BMY",  "FY2026-Q2", "2026-07-30T12:15:00+00:00", "2026-07-30T12:15:00+00:00", 5929),
    ("BSX",  "FY2026-Q2", "2026-07-29T12:00:00+00:00", "2026-07-29T12:00:00+00:00", 5155),
    ("CI",   "FY2026-Q2", "2026-07-30T12:30:00+00:00", "2026-07-30T12:30:00+00:00", 4370),
    ("DHR",  "FY2026-Q2", "2026-07-21T12:00:00+00:00", "2026-07-21T12:00:00+00:00", 3685),
    ("ELV",  "FY2026-Q2", "2026-07-15T12:30:00+00:00", "2026-07-15T12:30:00+00:00", 3742),
    ("GILD", "FY2026-Q2", "2026-08-04T20:30:00+00:00", "2026-08-04T20:30:00+00:00", 5113),
    ("ISRG", "FY2026-Q2", "2026-07-16T20:30:00+00:00", "2026-07-16T20:30:00+00:00", 6078),
    ("JNJ",  "FY2026-Q2", "2026-07-15T12:30:00+00:00", "2026-07-15T12:30:00+00:00", 5162),
    ("LLY",  "FY2026-Q2", "2026-08-05T14:00:00+00:00", "2026-08-05T14:00:00+00:00", 5159),
    ("MDT",  "FY2026-Q4", "2026-06-03T11:45:00+00:00", "2026-06-03T11:45:00+00:00", 4054),
    ("MRK",  "FY2026-Q2", "2026-08-04T13:00:00+00:00", "2026-08-04T13:00:00+00:00", 10993),
    ("PFE",  "FY2026-Q2", "2026-08-04T14:00:00+00:00", "2026-08-04T14:00:00+00:00", 4144),
    ("REGN", "FY2026-Q2", "2026-07-30T12:30:00+00:00", "2026-07-30T12:30:00+00:00", 5431),
    ("SYK",  "FY2026-Q2", "2026-07-30T20:30:00+00:00", "2026-07-30T20:30:00+00:00", 4857),
    ("TMO",  "FY2026-Q2", "2026-07-23T12:30:00+00:00", "2026-07-23T12:30:00+00:00", 4878),
    ("UNH",  "FY2026-Q2", "2026-07-16T12:00:00+00:00", "2026-07-16T12:00:00+00:00", 4258),
    ("VRTX", "FY2026-Q2", "2026-08-03T20:30:00+00:00", "2026-08-03T20:30:00+00:00", 6557),
]


@dataclass
class BatchResult:
    ticker: str
    period: str
    ok: bool
    returncode: int
    output: str


def run_onboard(
    ticker: str,
    period: str,
    report_at: str,
    call_at: str,
    quartr_company_id: int,
    *,
    dry_run: bool = False,
) -> BatchResult:
    cmd = [
        sys.executable, "-m", "services.earnings_monitor.cli",
        "onboard",
        "--ticker", ticker,
        "--period", period,
        "--report-at", report_at,
        "--call-at", call_at,
        "--quartr-company-id", str(quartr_company_id),
        "--research-sector", "xlv_hc",
        "--skip-pull",
        "--skip-quant",
        "--skip-llm",
        "--skip-panel",
        "--force-onboard",
    ]
    if dry_run:
        cmd.append("--dry-run")

    print(f"\n{'='*60}")
    print(f"  Onboarding {ticker} {period}  (quartr_id={quartr_company_id})")
    if dry_run:
        print("  [DRY RUN]")
    print(f"{'='*60}")
    print(f"  cmd: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=False,   # stream stdout/stderr live
        text=True,
    )
    ok = result.returncode == 0
    status = "OK" if ok else f"FAILED (rc={result.returncode})"
    print(f"\n  [{ticker}] {status}")
    return BatchResult(
        ticker=ticker,
        period=period,
        ok=ok,
        returncode=result.returncode,
        output="",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="HC large-cap batch onboard")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to each onboard")
    parser.add_argument(
        "--tickers", nargs="+",
        help="Only run these tickers (default: all 20 HC)",
    )
    args = parser.parse_args()

    targets = HC_TICKERS
    if args.tickers:
        wanted = {t.upper() for t in args.tickers}
        targets = [row for row in HC_TICKERS if row[0] in wanted]
        print(f"Filtered to {len(targets)} ticker(s): {[r[0] for r in targets]}")

    failures: list[BatchResult] = []
    for ticker, period, report_at, call_at, cid in targets:
        r = run_onboard(
            ticker, period, report_at, call_at, cid,
            dry_run=args.dry_run,
        )
        if not r.ok:
            failures.append(r)

    print("\n" + "="*60)
    print(f"  BATCH COMPLETE — {len(targets) - len(failures)}/{len(targets)} succeeded")
    if failures:
        print(f"  FAILURES: {[f.ticker for f in failures]}")
        return 1
    print("  All onboards completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
