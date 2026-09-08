"""
_desk_call_scorecard.py
=======================
Compute a per-(ticker, fiscal_period) 2-axis scorecard for the claims desk:

  Delivery score  — rolling known_delivered_rate up to and including the call
  Engagement score — signed measure of whether management strengthened or
                     weakened its commitments *during* that specific quarter

Output: data/desk_call_scorecard_v1.json

Usage
-----
    python scripts/_desk_call_scorecard.py            # write JSON
    python scripts/_desk_call_scorecard.py --print    # pretty-print to stdout
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "desk_call_scorecard_v1.json"

BOOK_PATHS: dict[str, Path] = {
    "nvda_gold_v2":  ROOT / "Structured Narrative/output/cross_company/json/desk_trees_v2.json",
    "desk_ops_v2":   ROOT / "Structured Narrative/output/cross_company/json/desk_trees_ops_v2.json",
    "desk_hc_v2":    ROOT / "Structured Narrative/output/cross_company/json/desk_trees_hc_v2.json",
}

# Edges that count as explicit terminal-negative at a call
NEGATIVE_TERMINAL_EDGES = {"missed", "dropped", "abandoned", "expired"}
# Edges that count as positive reaffirmation
POSITIVE_EDGES = {"restated"}
# Edges that count as delay / hedge
DEFERRAL_EDGES = {"deferred"}
# Edges that are purely terminal/settled — not in-flight at all
ALL_TERMINAL_EDGES = {
    "delivered", "missed", "dropped", "abandoned", "expired",
    "hit", "still-want", "harden-to-promise",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fiscal_key(fp: str) -> tuple[int, int]:
    """'FY2024-Q3' -> (2024, 3) for sorting."""
    try:
        year_part, q_part = fp.split("-")
        return (int(year_part[2:]), int(q_part[1:]))
    except Exception:
        return (0, 0)


def _load_book(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[scorecard] warning: could not load {path}: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Core computation
# ---------------------------------------------------------------------------

def _scorecard_for_book(book: dict[str, Any], book_id: str) -> list[dict[str, Any]]:
    """
    Given a book dict (with 'trees' list), return one scorecard entry per
    (ticker, fiscal_period) pair that has meaningful activity.

    Activity = any quarter in which >=1 tree has a seed or a node.
    """
    trees: list[dict] = book.get("trees") or []

    # ------------------------------------------------------------------ #
    # 1.  Index trees by ticker                                           #
    # ------------------------------------------------------------------ #
    ticker_trees: dict[str, list[dict]] = defaultdict(list)
    for t in trees:
        ticker_trees[t["ticker"]].append(t)

    # ------------------------------------------------------------------ #
    # 2.  For each ticker, find every active quarter                      #
    # ------------------------------------------------------------------ #
    entries: list[dict[str, Any]] = []

    for ticker, ttrees in sorted(ticker_trees.items()):
        # Collect all quarters that have any event (seed or node)
        all_quarters: set[str] = set()
        for t in ttrees:
            all_quarters.add(t["seed"]["fiscal_period"])
            for n in t.get("nodes") or []:
                all_quarters.add(n["fiscal_period"])

        sorted_quarters = sorted(all_quarters, key=fiscal_key)

        for q in sorted_quarters:
            entry = _score_ticker_at_quarter(ticker, q, ttrees, book_id)
            if entry is not None:
                entries.append(entry)

    return entries


def _score_ticker_at_quarter(
    ticker: str,
    q: str,
    trees: list[dict],
    book_id: str,
) -> dict[str, Any] | None:
    """
    Compute delivery + engagement scores for `ticker` at call `q`.

    Returns None if the quarter has no meaningful data (e.g. pre-history).
    """
    q_key = fiscal_key(q)

    # ------------------------------------------------------------------ #
    # Delivery score — rolling known_delivered_rate up to and incl. Q    #
    # ------------------------------------------------------------------ #
    # A tree is "aged" (settled) as of Q if its terminal edge's fiscal_period <= Q
    # confirmed = delivered/hit | failed = missed/dropped/abandoned | withdrawn = abandoned (subset)
    n_confirmed = 0
    n_failed = 0
    n_withdrawn = 0

    for t in trees:
        terminal_edge = None
        terminal_fp = None
        for n in (t.get("nodes") or []):
            if n["edge"] in ALL_TERMINAL_EDGES and fiscal_key(n["fiscal_period"]) <= q_key:
                terminal_edge = n["edge"]
                terminal_fp = n["fiscal_period"]

        if terminal_edge in {"delivered", "hit"}:
            n_confirmed += 1
        elif terminal_edge in {"missed", "dropped", "abandoned", "expired"}:
            n_failed += 1
            if terminal_edge == "abandoned":
                n_withdrawn += 1

    n_aged = n_confirmed + n_failed
    delivery_score: float | None = (n_confirmed / n_aged) if n_aged > 0 else None

    # ------------------------------------------------------------------ #
    # Engagement score — signals from this specific quarter Q            #
    # ------------------------------------------------------------------ #
    # open_trees_at_Q = seeded before Q, not yet terminally settled as of Q-1
    prev_q_key = _prev_quarter_key(q_key)

    open_trees_at_q: list[dict] = []
    for t in trees:
        seed_fp_key = fiscal_key(t["seed"]["fiscal_period"])
        if seed_fp_key >= q_key:
            continue  # seeded in Q or later — not yet open at start of Q
        # Check if it was already terminated BEFORE Q
        terminal_before_q = any(
            n["edge"] in ALL_TERMINAL_EDGES and fiscal_key(n["fiscal_period"]) < q_key
            for n in (t.get("nodes") or [])
        )
        if not terminal_before_q:
            open_trees_at_q.append(t)

    # New seeds introduced AT Q
    new_seed_trees = [t for t in trees if fiscal_key(t["seed"]["fiscal_period"]) == q_key]
    n_new_seeds = len(new_seed_trees)

    # Categorise each open tree's signal AT Q
    n_restated = 0
    n_deferred = 0
    n_dropped_at_q = 0
    n_has_node_at_q = 0

    for t in open_trees_at_q:
        node_at_q = next(
            (n for n in (t.get("nodes") or []) if n["fiscal_period"] == q),
            None,
        )
        if node_at_q is None:
            continue  # silent — counted below
        n_has_node_at_q += 1
        edge = node_at_q["edge"]
        if edge in POSITIVE_EDGES:
            n_restated += 1
        elif edge in DEFERRAL_EDGES:
            n_deferred += 1
        elif edge in NEGATIVE_TERMINAL_EDGES:
            n_dropped_at_q += 1

    n_silent = len(open_trees_at_q) - n_has_node_at_q  # implicitly skipped

    # ------------------------------------------------------------------ #
    # Open-goal health: never-touched + stale                             #
    # ------------------------------------------------------------------ #
    # n_never_touched: open trees with ZERO nodes in their entire history
    #   (seeded but management has never followed up in any quarter)
    n_never_touched = sum(
        1 for t in open_trees_at_q if not t.get("nodes")
    )

    # n_open_stale: open trees with no node in the 4 quarters ending at Q
    #   (they may have been touched once, but not recently)
    stale_window = 4
    stale_cutoff_key = q_key[0] * 10 + q_key[1] - stale_window
    # Adjust for year wrap
    stale_cutoff_year = q_key[0] - (stale_window // 4)
    stale_cutoff_q = q_key[1] - (stale_window % 4)
    if stale_cutoff_q <= 0:
        stale_cutoff_year -= 1
        stale_cutoff_q += 4
    stale_cutoff = (stale_cutoff_year, stale_cutoff_q)

    n_open_stale = 0
    for t in open_trees_at_q:
        last_touch = max(
            (fiscal_key(n["fiscal_period"]) for n in (t.get("nodes") or [])),
            default=fiscal_key(t["seed"]["fiscal_period"]),
        )
        if last_touch < stale_cutoff:
            n_open_stale += 1

    # Signed engagement formula
    denominator = max(1, len(open_trees_at_q) + n_new_seeds)
    raw = (
        n_restated
        + n_new_seeds
        - n_dropped_at_q
        - n_deferred
        - (n_silent * 0.5)
    )
    engagement_score = max(-1.0, min(1.0, raw / denominator))

    # Skip quarters with zero information (no open trees, no new seeds)
    if len(open_trees_at_q) == 0 and n_new_seeds == 0:
        return None

    return {
        "ticker": ticker,
        "fiscal_period": q,
        "book_id": book_id,
        # Delivery
        "delivery_score": round(delivery_score, 4) if delivery_score is not None else None,
        "n_confirmed": n_confirmed,
        "n_failed": n_failed,
        "n_withdrawn": n_withdrawn,
        "n_aged": n_aged,
        # Engagement
        "engagement_score": round(engagement_score, 4),
        "n_restated": n_restated,
        "n_new_seeds": n_new_seeds,
        "n_deferred": n_deferred,
        "n_dropped": n_dropped_at_q,
        "n_silent": n_silent,
        "open_trees_at_call": len(open_trees_at_q),
        # Open-goal health
        "n_never_touched": n_never_touched,
        "n_open_stale": n_open_stale,
        "pct_never_touched": round(n_never_touched / len(open_trees_at_q), 4) if open_trees_at_q else 0.0,
    }


def _prev_quarter_key(q_key: tuple[int, int]) -> tuple[int, int]:
    year, q = q_key
    if q == 1:
        return (year - 1, 4)
    return (year, q - 1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def build_scorecard() -> dict[str, Any]:
    all_entries: list[dict] = []

    for book_id, path in BOOK_PATHS.items():
        book = _load_book(path)
        if book is None:
            print(f"[scorecard] skipping {book_id} — file not found", file=sys.stderr)
            continue
        entries = _scorecard_for_book(book, book_id)
        all_entries.extend(entries)
        tickers = sorted({e["ticker"] for e in entries})
        print(
            f"[scorecard] {book_id}: {len(entries)} entries, "
            f"{len(tickers)} tickers: {tickers}",
            file=sys.stderr,
        )

    # Sort: book_id, ticker, fiscal_period
    all_entries.sort(key=lambda e: (e["book_id"], e["ticker"], fiscal_key(e["fiscal_period"])))

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "schema_version": 1,
        "n_entries": len(all_entries),
        "entries": all_entries,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build claims desk call scorecard")
    parser.add_argument("--print", action="store_true", dest="print_only",
                        help="Pretty-print to stdout instead of writing file")
    args = parser.parse_args()

    scorecard = build_scorecard()

    if args.print_only:
        print(json.dumps(scorecard, indent=2))
    else:
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(scorecard, indent=2), encoding="utf-8")
        print(f"[scorecard] wrote {OUT_PATH} ({scorecard['n_entries']} entries)")


if __name__ == "__main__":
    main()
