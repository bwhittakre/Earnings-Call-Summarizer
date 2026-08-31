"""Print exact leftover excerpts that match a substring."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    ticker = sys.argv[1].upper()
    needle = " ".join(sys.argv[2:]).lower()
    path = (
        ROOT
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / f"desk_cue_queue_v2_{ticker}.json"
    )
    queue = json.loads(path.read_text(encoding="utf-8"))
    for row in queue.get("missed") or []:
        excerpt = str(row.get("excerpt") or "")
        if needle in excerpt.lower():
            print(json.dumps(row, indent=2))
            print("---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
