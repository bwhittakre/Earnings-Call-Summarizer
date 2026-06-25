#!/usr/bin/env python3
"""Replay evidence_audit drops and report which bullets quote anchor would recover."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.paths import EVIDENCE_AUDIT_DIR
from src.validation.quote_anchor import find_verbatim_quote

DEFAULT_AUDIT_DIR = EVIDENCE_AUDIT_DIR


def replay_audit_file(path: Path, source_map: dict[str, str]) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    label = payload.get("label", path.stem)
    source_text = source_map.get(label, "")
    dropped = payload.get("dropped", [])
    recoverable: list[dict] = []
    still_dropped: list[dict] = []

    for entry in dropped:
        claim = entry.get("claim", "")
        excerpt = entry.get("excerpt", "")
        canonical = entry.get("canonical_excerpt")
        quote = (
            find_verbatim_quote(
                claim,
                source_text,
                hint_excerpt=canonical or excerpt,
            )
            if source_text
            else None
        )
        result = {**entry, "anchor_quote": quote}
        if quote:
            recoverable.append(result)
        else:
            still_dropped.append(result)

    return {
        "file": str(path),
        "label": label,
        "dropped_count": len(dropped),
        "recoverable_count": len(recoverable),
        "recoverable": recoverable,
        "still_dropped": still_dropped,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--audit-dir",
        type=Path,
        default=DEFAULT_AUDIT_DIR,
        help="Directory containing evidence_audit JSON files",
    )
    parser.add_argument(
        "--source-file",
        type=Path,
        help="Optional JSON map of label -> source_text for replay",
    )
    args = parser.parse_args()

    source_map: dict[str, str] = {}
    if args.source_file and args.source_file.exists():
        source_map = json.loads(args.source_file.read_text(encoding="utf-8"))

    audit_files = sorted(args.audit_dir.glob("*.json"))
    if not audit_files:
        print(f"No audit files found in {args.audit_dir}")
        return

    total_dropped = 0
    total_recoverable = 0
    for path in audit_files:
        report = replay_audit_file(path, source_map)
        total_dropped += report["dropped_count"]
        total_recoverable += report["recoverable_count"]
        print(
            f"{path.name}: dropped={report['dropped_count']} "
            f"recoverable={report['recoverable_count']}"
        )
        for entry in report["recoverable"]:
            print(
                f"  recoverable: [{entry.get('field')}:{entry.get('index')}] "
                f"{entry.get('claim')!r}"
            )

    print(
        f"\nSummary: {total_recoverable}/{total_dropped} dropped bullets "
        "would be recoverable by quote anchor (when source text is supplied)."
    )
    if not source_map:
        print(
            "Note: pass --source-file with a JSON map {label: source_text} "
            "to evaluate against real transcripts."
        )


if __name__ == "__main__":
    main()
