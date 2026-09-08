"""CRWV earnings history batch onboard.

Onboards CoreWeave (CRWV) across its 6 completed earnings quarters
(FY2025-Q1 through FY2026-Q2). After all quarters are registered,
kicks off the full-history desk seeding so CRWV is fully wired into
the claims desk.

What DOES run:
  - Quartr company_id (20310) written to overlay
  - Fiscal calendar registered in config/fiscal_calendars.yaml
  - Ticker added to config/sectors/xlk_tech.txt
  - Ticker registered in monitor.sqlite3
  - Full-history claims desk seeding via run_history_onboard_for_ticker

What SKIPS (data already on disk / not applicable):
  --skip-pull   (transcripts already pulled or will be pulled by SN)
  --skip-quant  (consensus not yet available for all quarters)
  --skip-llm    (LLM scoring handled by claims desk pipeline)
  --skip-panel  (panel ingestion not needed here)

Usage (from repo root, PowerShell):
    python scripts/_crwv_onboard_batch.py [--dry-run]
    python scripts/_crwv_onboard_batch.py --skip-desk-seed [--dry-run]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# (fiscal_period, call_date_iso, quartr_company_id)
CRWV_QUARTERS: list[tuple[str, str, int]] = [
    ("FY2025-Q1", "2025-05-14T20:00:00+00:00", 20310),
    ("FY2025-Q2", "2025-08-12T20:00:00+00:00", 20310),
    ("FY2025-Q3", "2025-11-10T21:00:00+00:00", 20310),
    ("FY2025-Q4", "2026-02-26T21:00:00+00:00", 20310),
    ("FY2026-Q1", "2026-05-07T20:00:00+00:00", 20310),
    ("FY2026-Q2", "2026-08-11T20:00:00+00:00", 20310),
]


@dataclass
class BatchResult:
    period: str
    ok: bool
    returncode: int


def run_onboard(
    period: str,
    call_at: str,
    quartr_company_id: int,
    *,
    dry_run: bool = False,
) -> BatchResult:
    cmd = [
        sys.executable, "-m", "services.earnings_monitor.cli",
        "onboard",
        "--ticker", "CRWV",
        "--period", period,
        "--report-at", call_at,
        "--call-at", call_at,
        "--quartr-company-id", str(quartr_company_id),
        "--research-sector", "xlk_tech",
        "--prior-event-count", "1",   # override: past-date onboard with no on-disk data
        "--skip-pull",
        "--skip-quant",
        "--skip-llm",
        "--skip-panel",
        "--force-onboard",
    ]
    if dry_run:
        cmd.append("--dry-run")

    print(f"\n{'='*60}")
    print(f"  Onboarding CRWV {period}")
    if dry_run:
        print("  [DRY RUN]")
    print(f"{'='*60}")
    print(f"  cmd: {' '.join(cmd)}")

    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=False,
        text=True,
    )
    ok = result.returncode == 0
    status = "OK" if ok else f"FAILED (rc={result.returncode})"
    print(f"\n  [CRWV {period}] {status}")
    return BatchResult(period=period, ok=ok, returncode=result.returncode)


def run_desk_seed(*, dry_run: bool = False) -> bool:
    """Call run_history_onboard_for_ticker for CRWV."""
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from scripts._desk_history_onboard import run_history_onboard_for_ticker  # type: ignore
        print(f"\n{'='*60}")
        print("  Running full-history desk seeding for CRWV …")
        print(f"{'='*60}")
        run_history_onboard_for_ticker("CRWV", dry_run=dry_run)
        print("  [CRWV] desk seeding OK")
        return True
    except ImportError:
        print(
            "  [WARN] _desk_history_onboard not found — "
            "skipping desk seeding. Run manually if needed.",
            file=sys.stderr,
        )
        return False
    except Exception as exc:
        print(f"  [ERROR] desk seeding failed: {exc}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="CRWV earnings history batch onboard")
    parser.add_argument("--dry-run", action="store_true",
                        help="Pass --dry-run to each onboard call")
    parser.add_argument("--skip-desk-seed", action="store_true",
                        help="Skip the full-history desk seeding step")
    parser.add_argument(
        "--quarters", nargs="+", metavar="PERIOD",
        help="Only run these fiscal periods (default: all 6)",
    )
    args = parser.parse_args()

    targets = CRWV_QUARTERS
    if args.quarters:
        wanted = {q.upper() for q in args.quarters}
        targets = [row for row in CRWV_QUARTERS if row[0].upper() in wanted]
        print(f"Filtered to {len(targets)} quarter(s): {[r[0] for r in targets]}")

    failures: list[BatchResult] = []
    for period, call_at, cid in targets:
        r = run_onboard(period, call_at, cid, dry_run=args.dry_run)
        if not r.ok:
            failures.append(r)

    print("\n" + "=" * 60)
    print(f"  EARNINGS ONBOARD COMPLETE — "
          f"{len(targets) - len(failures)}/{len(targets)} succeeded")
    if failures:
        print(f"  FAILURES: {[f.period for f in failures]}")

    # Full-history desk seeding
    if not args.skip_desk_seed and not args.dry_run:
        run_desk_seed(dry_run=args.dry_run)
    elif args.skip_desk_seed:
        print("  [skipped] desk seeding (--skip-desk-seed)")
    elif args.dry_run:
        print("  [skipped] desk seeding (dry-run mode)")

    if failures:
        return 1
    print("  All CRWV onboards completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
