#!/usr/bin/env python3
"""Run Roz onboard for Healthcare Large-Cap after Quartr MCP seed.

Do not use this for leftover history. Use scripts/_hc_leftover_history.py
(dry-run default; no run_onboard, no --force, tagged stamp only).

Does not append names into the live xlk_tech / SQLite Roz book.
Uses MCP-seeded transcripts_raw and --skip-pull.

  .venv\\Scripts\\python.exe scripts/_healthcare_onboard_batch.py
  .venv\\Scripts\\python.exe scripts/_healthcare_onboard_batch.py --ticker LLY
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SN = REPO / "Structured Narrative"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(SN) not in sys.path:
    sys.path.insert(0, str(SN))

from services.earnings_monitor.onboard import (  # noqa: E402
    discover_on_disk_periods,
    run_onboard,
)

CATALOG = REPO / "data" / "healthcare_large_cap" / "company_catalog.json"
STATUS = REPO / "data" / "healthcare_large_cap" / "onboard_status.json"
SECTOR = "healthcare_large_cap"
REPORT_AT = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)


def _load_catalog() -> list[dict]:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    return list(payload.get("companies") or [])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", action="append", default=[])
    parser.add_argument("--skip-llm", action="store_true")
    args = parser.parse_args()

    companies = _load_catalog()
    wanted = {t.strip().upper() for t in args.ticker if t.strip()}
    if wanted:
        companies = [c for c in companies if str(c.get("ticker", "")).upper() in wanted]
    tickers = [str(c["ticker"]).upper() for c in companies]
    names = {str(c["ticker"]).upper(): str(c.get("name") or c["ticker"]) for c in companies}

    STATUS.parent.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    if STATUS.is_file():
        try:
            prior = json.loads(STATUS.read_text(encoding="utf-8"))
            results = list(prior.get("results") or [])
        except json.JSONDecodeError:
            results = []

    for ticker in tickers:
        on_disk = discover_on_disk_periods(REPO, ticker)
        if len(on_disk) < 2:
            row = {
                "ticker": ticker,
                "status": "blocked",
                "error": f"Need >=2 MCP transcripts, found {on_disk}",
            }
            results.append(row)
            STATUS.write_text(
                json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "results": results}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            print(json.dumps(row))
            continue
        latest = on_disk[-1]
        result = run_onboard(
            repo_root=REPO,
            ticker=ticker,
            fiscal_period=latest,
            report_at=REPORT_AT,
            company_name=names.get(ticker, ticker),
            skip_pull=True,
            force_mode="onboard",
            skip_book_sync=True,
            research_sector=SECTOR,
            skip_llm=bool(args.skip_llm),
            configured_tickers=tickers,
        )
        row = result.to_dict()
        results.append(row)
        STATUS.write_text(
            json.dumps(
                {
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                    "results": results,
                },
                indent=2,
                default=str,
            )
            + "\n",
            encoding="utf-8",
        )
        print(json.dumps({"ticker": ticker, "status": result.status, "error": result.error}, default=str))
        if result.status == "failed":
            # Continue the remaining book; one hard fail must not stop the night.
            continue
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
