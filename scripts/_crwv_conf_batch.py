"""Batch-process all 12 historical CRWV conference transcripts.

Iterates over the completed conferences in chronological order,
calling _desk_conf_ingest.ingest_conference() for each.  The Goldman
Sachs event tonight (746055) is NOT included here; run that separately
once its transcript is available:

    python scripts/_desk_conf_ingest.py \\
        --ticker CRWV \\
        --event-id 746055 \\
        --event-date 2026-09-08 \\
        --event-name "Goldman Sachs 2026"

Usage (from repo root, PowerShell):
    python scripts/_crwv_conf_batch.py [--dry-run] [--extract-only]
    python scripts/_crwv_conf_batch.py --events 376104 380945   # subset
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# (event_id, date, name)
CRWV_CONFERENCES: list[tuple[int, str, str]] = [
    (376104, "2025-08-27", "Deutsche Bank 2025"),
    (380945, "2025-09-09", "Goldman Sachs 2025"),
    (421721, "2025-09-25", "Jefferies Virtual AI Summit 2025"),
    (418642, "2025-11-18", "Wells Fargo TMT 2025"),
    (483890, "2025-12-02", "BofA Leveraged Finance 2025"),
    (483891, "2025-12-03", "UBS Global Tech 2025"),
    (578086, "2026-03-04", "Morgan Stanley TMT 2026"),
    (578090, "2026-03-10", "Cantor Fitzgerald 2026"),
    (671041, "2026-05-19", "J.P. Morgan TMT 2026"),
    (679766, "2026-05-27", "Jefferies Software AI 2026"),
    (682572, "2026-06-03", "BofA Global Tech 2026"),
    (687670, "2026-06-08", "AGM 2026"),
]


@dataclass
class ConferenceResult:
    event_id: int
    name: str
    ok: bool
    n_rows: int
    error: str = ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and parse but do NOT write files or call LLM")
    parser.add_argument("--extract-only", action="store_true",
                        help="Extract and write cue file but do NOT run autopilot")
    parser.add_argument("--budget-usd", type=float, default=0.25,
                        help="Per-conference autopilot Sonnet budget (default 0.25)")
    parser.add_argument("--events", nargs="+", type=int, metavar="ID",
                        help="Only process these event IDs (default: all 12)")
    args = parser.parse_args()

    from scripts._desk_conf_ingest import ingest_conference  # noqa: E402

    targets = CRWV_CONFERENCES
    if args.events:
        wanted = set(args.events)
        targets = [row for row in CRWV_CONFERENCES if row[0] in wanted]
        print(f"Filtered to {len(targets)} conference(s): {[r[2] for r in targets]}")

    # Auto-detect per-event transcript files in data/conf_transcripts/CRWV/
    # Naming convention: {event_id}.json or {event_id}.txt
    transcript_dir = ROOT / "data" / "conf_transcripts" / "CRWV"

    results: list[ConferenceResult] = []
    for event_id, date, name in targets:
        # Look for a pre-downloaded transcript
        transcript_file = None
        for ext in (".json", ".txt"):
            candidate = transcript_dir / f"{event_id}{ext}"
            if candidate.exists():
                transcript_file = candidate
                break

        try:
            rows = ingest_conference(
                "CRWV",
                event_id,
                date,
                name,
                dry_run=args.dry_run,
                extract_only=args.extract_only,
                budget_usd=args.budget_usd,
                transcript_file=transcript_file,
            )
            results.append(ConferenceResult(
                event_id=event_id,
                name=name,
                ok=True,
                n_rows=len(rows),
            ))
        except Exception as exc:
            print(f"\n  [ERROR] {name} (event {event_id}): {exc}", file=sys.stderr)
            results.append(ConferenceResult(
                event_id=event_id,
                name=name,
                ok=False,
                n_rows=0,
                error=str(exc),
            ))

    # Summary
    print("\n" + "=" * 60)
    print(f"  CONFERENCE BATCH COMPLETE — "
          f"{sum(1 for r in results if r.ok)}/{len(results)} succeeded")
    total_rows = sum(r.n_rows for r in results)
    print(f"  Total supplemental cue rows extracted: {total_rows}")
    failures = [r for r in results if not r.ok]
    if failures:
        print("  FAILURES:")
        for f in failures:
            print(f"    [{f.event_id}] {f.name}: {f.error}")
        return 1

    print("  All conferences processed successfully.")
    print("\nNext step — once Goldman Sachs transcript is available tonight:")
    print("  python scripts/_desk_conf_ingest.py \\")
    print("      --ticker CRWV \\")
    print("      --event-id 746055 \\")
    print("      --event-date 2026-09-08 \\")
    print('      --event-name "Goldman Sachs 2026"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
