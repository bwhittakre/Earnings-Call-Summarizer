"""Census claims-desk onboard. Does not insert trees. Does not rewrite gold."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_trees_v2_hc import HC_TICKERS  # noqa: E402
from scripts._desk_trees_v2_ops import TECH_TICKERS  # noqa: E402

OUT = ROOT / "Structured Narrative" / "output"


def _novelty(ticker: str) -> bool:
    return (OUT / ticker / "json" / "novelty_view.json").is_file()


def _queue(ticker: str) -> dict:
    if ticker == "NVDA":
        path = OUT / "cross_company" / "json" / "desk_cue_queue_v2.json"
    else:
        path = OUT / "cross_company" / "json" / f"desk_cue_queue_v2_{ticker}.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _book_trees(ticker: str, book_id: str) -> int:
    name = {
        "nvda_gold_v2": "desk_trees_v2.json",
        "desk_ops_v2": "desk_trees_ops_v2.json",
        "desk_hc_v2": "desk_trees_hc_v2.json",
    }[book_id]
    path = OUT / "cross_company" / "json" / name
    if not path.is_file():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8"))
    return sum(
        1
        for tree in payload.get("trees") or []
        if str(tree.get("ticker") or "").upper() == ticker
    )


def main() -> int:
    rows = []
    for ticker in TECH_TICKERS:
        book = "nvda_gold_v2" if ticker == "NVDA" else "desk_ops_v2"
        queue = _queue(ticker)
        rows.append(
            {
                "ticker": ticker,
                "universe": "tech",
                "novelty": _novelty(ticker),
                "book": book,
                "trees": _book_trees(ticker, book),
                "seedable": queue.get("n_seedable"),
                "covered": queue.get("n_covered"),
                "leftover": queue.get("n_missed"),
            }
        )
    for ticker in HC_TICKERS:
        queue = _queue(ticker)
        rows.append(
            {
                "ticker": ticker,
                "universe": "healthcare",
                "novelty": _novelty(ticker),
                "book": "desk_hc_v2",
                "trees": _book_trees(ticker, "desk_hc_v2"),
                "seedable": queue.get("n_seedable"),
                "covered": queue.get("n_covered"),
                "leftover": queue.get("n_missed"),
            }
        )
    print(
        f"{'ticker':<6} {'univ':<11} nov book            trees seed cov left"
    )
    missing = []
    leftover = 0
    seedable = 0
    covered = 0
    for row in rows:
        print(
            f"{row['ticker']:<6} {row['universe']:<11} "
            f"{'Y' if row['novelty'] else 'N':<4}"
            f"{row['book']:<15} {row['trees']:>5} "
            f"{str(row['seedable']):>4} {str(row['covered']):>3} "
            f"{str(row['leftover']):>4}"
        )
        if not row["novelty"] or row["seedable"] is None:
            missing.append(row["ticker"])
        leftover += int(row["leftover"] or 0)
        seedable += int(row["seedable"] or 0)
        covered += int(row["covered"] or 0)
    print(
        f"n={len(rows)} missing={missing or 'none'} "
        f"seedable={seedable} covered={covered} leftover={leftover}"
    )
    dest = ROOT / "data" / "desk_onboard_census.json"
    dest.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
