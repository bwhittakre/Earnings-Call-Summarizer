"""Print asof / 0_56 periods in harness fiscal order. No Rank ICs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "Structured Narrative"))

from period_dates import calendar_quarter_sort_key  # noqa: E402
from services.earnings_monitor.dashboard.research_data import (  # noqa: E402
    load_rank_ic_bundle,
)

LABEL = "asof"
HORIZON = "0_56"


def main() -> None:
    rows = load_rank_ic_bundle(
        history_source=str(ROOT / "Structured Narrative" / "output")
    ).company_period
    periods = {
        str(row.get("period") or "")
        for row in rows
        if str(row.get("label_key") or "") == LABEL
        and str(row.get("horizon") or "") == HORIZON
        and str(row.get("period") or "")
    }
    ordered = sorted(periods, key=lambda p: calendar_quarter_sort_key(str(p)))
    mid = len(ordered) // 2
    payload = {
        "n": len(ordered),
        "early": ordered[:mid],
        "late": ordered[mid:],
        "all": ordered,
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
