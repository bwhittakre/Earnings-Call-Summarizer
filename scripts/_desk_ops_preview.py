"""Preview leftover seedable cues. Does not insert trees."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = (
    "continue to",
    "we will see",
    "we will take",
    "we will have",
    "we will make",
    "we will go",
    "we will update",
    "we will work",
    "we will invest",
    "we will support",
    "we will remain",
    "we will be",
    "we will do",
    "we expect to grow",
    "plus or minus",
)


def main() -> int:
    folder = ROOT / "Structured Narrative" / "output" / "cross_company" / "json"
    tickers = sys.argv[1:] or [
        "ADBE",
        "ADSK",
        "CRM",
        "IBM",
        "INTU",
        "MSFT",
        "ORCL",
    ]
    limit = 4
    for ticker in tickers:
        path = folder / f"desk_cue_queue_v2_{ticker}.json"
        if not path.is_file():
            print(f"==== {ticker} missing ====")
            continue
        queue = json.loads(path.read_text(encoding="utf-8"))
        print(f"==== {ticker} missed {queue.get('n_missed')} ====")
        kept = 0
        for row in queue.get("missed") or []:
            excerpt = str(row.get("excerpt") or "").replace("\n", " ")
            lowered = excerpt.lower()
            if any(token in lowered for token in SKIP):
                continue
            if row.get("class") not in {"promise", "goal"}:
                continue
            print(f"{row.get('fiscal_period')} {row.get('class')} {row.get('dimension')}")
            print(excerpt[:300])
            print()
            kept += 1
            if kept >= limit:
                break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
