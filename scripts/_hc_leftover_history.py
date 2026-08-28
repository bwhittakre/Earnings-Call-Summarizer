#!/usr/bin/env python3
"""Overnight leftover-history prep. Default is dry-run. Does not score.

Expands the seven leftover overlays to every on-disk transcript, then
(optionally) scores with run_universe_batch without --force. Healthcare
Rank IC stamp must use --output-tag healthcare_large_cap.

  python scripts/_hc_leftover_history.py
  python scripts/_hc_leftover_history.py --apply-overlays
  python scripts/_hc_leftover_history.py --score
  python scripts/_hc_leftover_history.py --stamp

Never calls run_onboard. Never writes live xlk_tech / SQLite Roz.
Never passes --force. Never starts keep-awake unless --keep-awake.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
SN = REPO / "Structured Narrative"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(SN) not in sys.path:
    sys.path.insert(0, str(SN))

from services.earnings_monitor.onboard import (  # noqa: E402
    discover_on_disk_periods,
    register_overlay_profile,
    scaffold_quarters_from_periods,
    write_company_overlay,
)

LEFTOVERS = ("LLY", "UNH", "DHR", "SYK", "GILD", "VRTX", "ELV")
ONBOARDED = (
    "ABBV",
    "ABT",
    "AMGN",
    "BMY",
    "BSX",
    "CI",
    "ISRG",
    "JNJ",
    "MDT",
    "MRK",
    "PFE",
    "REGN",
    "TMO",
)
HEALTHCARE_BOOK = ONBOARDED + LEFTOVERS
TWO_Q_OUTPUT = ("FY2026-Q1", "FY2026-Q2")
LLOYDS_ISIN = "GB0005163141"
HEALTHCARE_TAG = "healthcare_large_cap"
LOCKED_TECH_STAMP = "2026-08-17T17:28:40+00:00"
MIN_CALENDAR_QUARTER = "2016-Q2"

IDENTITY: dict[str, dict[str, str]] = {
    "LLY": {
        "isin": "US5324571083",
        "estpermid": "30064846182",
        "barra_id": "USAI951",
        "name": "Eli Lilly and Company",
    },
    "UNH": {
        "isin": "US91324P1021",
        "estpermid": "30064860782",
        "barra_id": "USAO6Z1",
        "name": "UnitedHealth Group",
    },
    "DHR": {
        "isin": "US2358511028",
        "estpermid": "30064836230",
        "barra_id": "USADTY1",
        "name": "Danaher",
    },
    "SYK": {
        "isin": "US8636671013",
        "estpermid": "30064857950",
        "barra_id": "USAN4Z1",
        "name": "Stryker",
    },
    "GILD": {
        "isin": "US3755581036",
        "estpermid": "30064840651",
        "barra_id": "USAREJ1",
        "name": "Gilead Sciences",
    },
    "VRTX": {
        "isin": "US92532F1003",
        "estpermid": "30064861819",
        "barra_id": "USAOKE1",
        "name": "Vertex Pharmaceuticals",
    },
    "ELV": {
        "isin": "US0367521038",
        "estpermid": "30064829391",
        "barra_id": "USA4NM1",
        "name": "Elevance Health",
    },
}


def _overlay_path(ticker: str) -> Path:
    return SN / "config" / "company_overlays" / f"{ticker}.json"


def _load_overlay(ticker: str) -> dict[str, Any]:
    path = _overlay_path(ticker)
    if not path.is_file():
        raise SystemExit(f"missing overlay {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SystemExit(f"malformed overlay {path}")
    return payload


def overlay_is_expanded(payload: dict[str, Any]) -> bool:
    output = tuple(payload.get("output_quarters") or ())
    return len(output) > len(TWO_Q_OUTPUT)


def proposed_scaffold(ticker: str) -> tuple[list[str], list[str], list[str]]:
    on_disk = discover_on_disk_periods(REPO, ticker)
    prior, output = scaffold_quarters_from_periods(on_disk)
    return on_disk, prior, output


def leftover_plan() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for ticker in LEFTOVERS:
        current = _load_overlay(ticker)
        isin = str(current.get("isin") or "")
        if isin == LLOYDS_ISIN:
            raise SystemExit(f"{ticker} overlay still has Lloyds ISIN {LLOYDS_ISIN}")
        expected = IDENTITY[ticker]
        if isin != expected["isin"]:
            raise SystemExit(f"{ticker} overlay ISIN {isin} != {expected['isin']}")
        on_disk, prior, output = proposed_scaffold(ticker)
        rows.append(
            {
                "ticker": ticker,
                "isin": isin,
                "estpermid": current.get("estpermid"),
                "transcripts": len(on_disk),
                "current_prior": list(current.get("prior_quarters") or []),
                "current_output": list(current.get("output_quarters") or []),
                "proposed_prior": prior,
                "proposed_output": output,
                "expanded": overlay_is_expanded(current),
                "already_scored_two_q": list(TWO_Q_OUTPUT),
            }
        )
    return {
        "dry_run": True,
        "leftovers": list(LEFTOVERS),
        "locked_tech_generated_at": LOCKED_TECH_STAMP,
        "healthcare_output_tag": HEALTHCARE_TAG,
        "score_command": [
            sys.executable,
            str(SN / "run_universe_batch.py"),
            "--tickers",
            *LEFTOVERS,
            "--batch",
        ],
        "stamp_command": [
            sys.executable,
            str(SN / "evaluate_narrative_signals.py"),
            "--tickers",
            *HEALTHCARE_BOOK,
            "--min-calendar-quarter",
            MIN_CALENDAR_QUARTER,
            "--output-tag",
            HEALTHCARE_TAG,
        ],
        "never": [
            "run_onboard",
            "--force",
            "skip_book_sync=false",
            "untagged evaluate_narrative_signals",
            "_healthcare_onboard_watch.py",
        ],
        "keep_awake_windows": (
            "Do not start keep-awake from this script unless --keep-awake. "
            "Overnight: presentationsettings or a SetThreadExecutionState loop."
        ),
        "names": rows,
    }


def apply_overlays() -> list[dict[str, Any]]:
    written: list[dict[str, Any]] = []
    for ticker in LEFTOVERS:
        current = _load_overlay(ticker)
        ident = IDENTITY[ticker]
        _on_disk, prior, output = proposed_scaffold(ticker)
        if not prior or not output:
            raise SystemExit(f"{ticker}: need prior + output from on-disk transcripts")
        path = write_company_overlay(
            REPO,
            ticker=ticker,
            company_name=str(current.get("company_name") or ident["name"]),
            prior_quarters=prior,
            output_quarters=output,
            estpermid=int(current.get("estpermid") or ident["estpermid"]),
            isin=str(current.get("isin") or ident["isin"]),
            barra_id=str(current.get("barra_id") or ident["barra_id"]),
        )
        register_overlay_profile(REPO, ticker)
        written.append(
            {
                "ticker": ticker,
                "path": str(path),
                "prior": prior,
                "output_n": len(output),
            }
        )
    return written


def assert_overlays_expanded() -> None:
    short = [t for t in LEFTOVERS if not overlay_is_expanded(_load_overlay(t))]
    if short:
        raise SystemExit(
            "overlays still two-quarter for "
            + ", ".join(short)
            + ". Run --apply-overlays first. Refusing --score/--stamp."
        )


def assert_panels_exist(tickers: tuple[str, ...]) -> None:
    missing = []
    for ticker in tickers:
        csv_path = SN / "output" / ticker / "csv" / "feature_panel.csv"
        if not csv_path.is_file():
            missing.append(ticker)
    if missing:
        raise SystemExit("feature_panel.csv missing for " + ", ".join(missing))


def run_score() -> int:
    assert_overlays_expanded()
    cmd = leftover_plan()["score_command"]
    print("Running (no --force):", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(REPO))


def run_stamp() -> int:
    assert_overlays_expanded()
    assert_panels_exist(HEALTHCARE_BOOK)
    cmd = leftover_plan()["stamp_command"]
    if "--output-tag" not in cmd or HEALTHCARE_TAG not in cmd:
        raise SystemExit("stamp command must include --output-tag healthcare_large_cap")
    print("Running tagged stamp:", " ".join(cmd))
    return subprocess.call(cmd, cwd=str(REPO))


def start_keep_awake() -> None:
    # Windows: request system/display away-mode. Caller must leave it running.
    script = (
        "Add-Type -Namespace Overnight -Name Native -MemberDefinition '"
        "[DllImport(\"kernel32.dll\")] public static extern uint "
        "SetThreadExecutionState(uint esFlags);'; "
        "[Overnight.Native]::SetThreadExecutionState(0x80000000 -bor 0x00000001 "
        "-bor 0x00000002) | Out-Null; "
        "Write-Host 'KEEP_AWAKE_ON'; while ($true) { Start-Sleep -Seconds 60 }"
    )
    subprocess.Popen(
        ["powershell", "-NoProfile", "-Command", script],
        cwd=str(REPO),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply-overlays",
        action="store_true",
        help="Rewrite leftover overlays to full on-disk history. Does not score.",
    )
    parser.add_argument(
        "--score",
        action="store_true",
        help="run_universe_batch on the seven leftovers without --force.",
    )
    parser.add_argument(
        "--stamp",
        action="store_true",
        help="evaluate_narrative_signals --output-tag healthcare_large_cap.",
    )
    parser.add_argument(
        "--keep-awake",
        action="store_true",
        help="Start a Windows keep-awake loop. Off by default.",
    )
    args = parser.parse_args()
    if args.keep_awake:
        start_keep_awake()
    if args.apply_overlays:
        written = apply_overlays()
        print(json.dumps({"applied_overlays": written}, indent=2))
    if args.score:
        return run_score()
    if args.stamp:
        return run_stamp()
    if not args.apply_overlays:
        plan = leftover_plan()
        plan["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(json.dumps(plan, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
