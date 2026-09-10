"""Independent case-study FY onboard for DDOG and LITE.

Reads data/case_study_pull/inventory.json. Only onboards earnings periods
that already have transcripts_raw/{TICKER}_{PERIOD}.txt. Does not join XLK
or mark Rank IC dirty.

Usage:
    python scripts/_case_study_onboard_batch.py --ticker DDOG
    python scripts/_case_study_onboard_batch.py --ticker LITE --skip-history-onboard
    python scripts/_case_study_onboard_batch.py --ticker DDOG --quarters FY2026-Q2
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INV = ROOT / "data" / "case_study_pull" / "inventory.json"
RAW = ROOT / "Structured Narrative" / "transcripts_raw"

META = {
    "DDOG": {
        "isin": "US23804L1035",
        "company_id": 6106,
        "industry_group": "tech",
        "company_name": "Datadog",
    },
    "LITE": {
        "isin": "US55024U1097",
        "company_id": 6193,
        "industry_group": "tech",
        "company_name": "Lumentum",
    },
}


def _as_of(iso: str) -> str:
    raw = iso.replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - timedelta(hours=1)).isoformat()


def earnings_rows(ticker: str) -> list[dict]:
    inv = json.loads(INV.read_text(encoding="utf-8"))
    rows = []
    for ev in inv[ticker]["events"]:
        if ev.get("kind") != "earnings":
            continue
        if ev.get("upcoming") or not ev.get("transcript_available"):
            continue
        period = ev.get("period")
        if not period:
            continue
        if not (RAW / f"{ticker}_{period}.txt").is_file():
            continue
        rows.append(ev)
    rows.sort(key=lambda r: str(r.get("date") or ""))
    return rows


def run_one(
    ticker: str,
    period: str,
    report_at: str,
    *,
    skip_history: bool,
    skip_quant: bool,
    dry_run: bool,
) -> int:
    meta = META[ticker]
    cmd = [
        sys.executable,
        "-m",
        "services.earnings_monitor.cli",
        "onboard",
        "--ticker",
        ticker,
        "--period",
        period,
        "--report-at",
        report_at,
        "--call-at",
        report_at,
        "--as-of",
        _as_of(report_at),
        "--company-name",
        meta["company_name"],
        "--quartr-company-id",
        str(meta["company_id"]),
        "--isin",
        meta["isin"],
        "--research-sector",
        "independent",
        "--industry-group",
        meta["industry_group"],
        "--skip-pull",
        "--force-onboard",
        "--prior-event-count",
        "1",
        "--history-budget-usd",
        "15",
    ]
    if skip_history:
        cmd.append("--skip-history-onboard")
    if skip_quant:
        cmd.append("--skip-quant")
        cmd.append("--skip-ids")
    if dry_run:
        cmd.append("--dry-run")
    print(" ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(ROOT)).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", required=True, choices=sorted(META))
    parser.add_argument("--quarters", nargs="+")
    parser.add_argument("--skip-history-onboard", action="store_true")
    parser.add_argument("--skip-quant", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    ticker = args.ticker.upper()
    rows = earnings_rows(ticker)
    if args.quarters:
        wanted = {q.upper() for q in args.quarters}
        rows = [r for r in rows if str(r.get("period")).upper() in wanted]
    if not rows:
        print(f"No on-disk earnings for {ticker}", file=sys.stderr)
        return 1
    failures = []
    for i, row in enumerate(rows):
        last = i == len(rows) - 1
        skip_hist = args.skip_history_onboard or not last
        rc = run_one(
            ticker,
            str(row["period"]),
            str(row["date"]),
            skip_history=skip_hist,
            skip_quant=args.skip_quant,
            dry_run=args.dry_run,
        )
        status = "OK" if rc == 0 else f"FAIL {rc}"
        print(f"[{ticker} {row['period']}] {status}", flush=True)
        if rc != 0:
            failures.append(row["period"])
    print(f"done {ticker}: {len(rows) - len(failures)}/{len(rows)}")
    if failures:
        print("failures", failures)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
