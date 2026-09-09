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
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.earnings_monitor.period_keys import (  # noqa: E402
    canonical_period as _canonical_period,
    fiscal_key as _fiscal_key,
    period_kind,
    period_sort_key,
    seed_before_call,
)
OUT_PATH = ROOT / "data" / "desk_call_scorecard_v1.json"

BOOK_PATHS: dict[str, Path] = {
    "nvda_gold_v2":  ROOT / "Structured Narrative/output/cross_company/json/desk_trees_v2.json",
    "desk_ops_v2":   ROOT / "Structured Narrative/output/cross_company/json/desk_trees_ops_v2.json",
    "desk_hc_v2":    ROOT / "Structured Narrative/output/cross_company/json/desk_trees_hc_v2.json",
}
BOOK_OVERLAY: dict[str, str] = {
    "desk_ops_v2": "ops",
    "desk_hc_v2": "hc",
}

_FY_RE = re.compile(r"^FY(\d{4})-Q([1-4])$", re.IGNORECASE)
_CONF_RE = re.compile(r"^CONF-(\d{4})-(\d{2})-(\d{2})$")

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

# Quarters a promise can stay open before counting as a soft miss in delivery rate
HORIZON_QTRS = 8

# Commitment-type hardness ranking — lower index = softer/weaker.
# A tree whose current_kind is below its original kind has been walked back.
KIND_HARDNESS: list[str] = [
    "aspiration",
    "soft_commitment",
    "guidance",
    "target",
    "promise",
    "hard_target",
]


def _kind_rank(k: str) -> int:
    try:
        return KIND_HARDNESS.index(k)
    except ValueError:
        return -1


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def canonical_period(fp: str) -> str:
    """Delivery-math only: map CONF stamps onto a calendar FY quarter."""
    return _canonical_period(fp)


def fiscal_key(fp: str) -> tuple[int, int]:
    """Canonical (year, quarter) for delivery / age. Unknown → (0, 0)."""
    return _fiscal_key(fp)


def _registry_fy_periods(ticker: str) -> set[str]:
    path = (
        ROOT
        / "Structured Narrative"
        / "output"
        / ticker.upper()
        / "json"
        / "quarter_registry.json"
    )
    if not path.is_file():
        return set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    scored = payload.get("scored_quarters") or {}
    return {str(p) for p in scored if period_kind(str(p)) == "fy"}


def _conf_cue_events(ticker: str) -> dict[str, str]:
    """CONF-YYYY-MM-DD → event name from the supplemental cue file."""
    path = ROOT / "data" / f"desk_conf_cue_{ticker.upper()}.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: dict[str, str] = {}
    for event in payload.get("events") or []:
        day = str(event.get("date") or "").strip()
        if not day:
            continue
        key = f"CONF-{day}"
        if period_kind(key) == "conf":
            out[key] = str(event.get("name") or "").strip()
    return out


def _collect_call_periods(ticker: str, ttrees: list[dict]) -> set[str]:
    """Raw FY + CONF labels: tree seeds/nodes, Roz registry, conference cues."""
    periods: set[str] = set()
    for t in ttrees:
        seed_fp = str((t.get("seed") or {}).get("fiscal_period") or "").strip()
        if period_kind(seed_fp) in {"fy", "conf"}:
            periods.add(seed_fp)
        for n in t.get("nodes") or []:
            node_fp = str(n.get("fiscal_period") or "").strip()
            if period_kind(node_fp) in {"fy", "conf"}:
                periods.add(node_fp)
    periods.update(_registry_fy_periods(ticker))
    periods.update(_conf_cue_events(ticker))
    return periods


def _load_book(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[scorecard] warning: could not load {path}: {exc}", file=sys.stderr)
        return None


def _merge_overlay_trees(book: dict[str, Any], overlay_key: str) -> dict[str, Any]:
    """Union compiled-book trees with overlay trees (overlay wins on id)."""
    try:
        from scripts._desk_catalog_overlay import get_overlay_trees, load_overlay
    except Exception as exc:
        print(f"[scorecard] warning: overlay import failed: {exc}", file=sys.stderr)
        return book

    overlay = load_overlay(overlay_key)
    extras = get_overlay_trees(overlay)
    if not extras:
        return book

    by_id: dict[str, dict] = {}
    for tree in book.get("trees") or []:
        tid = str(tree.get("tree_id") or "")
        if tid:
            by_id[tid] = tree
    for tree in extras:
        tid = str(tree.get("tree_id") or "")
        if tid:
            by_id[tid] = tree

    merged = dict(book)
    merged["trees"] = list(by_id.values())
    return merged


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
        cue_names = _conf_cue_events(ticker)
        all_calls = _collect_call_periods(ticker, ttrees)
        sorted_calls = sorted(all_calls, key=period_sort_key)

        for q in sorted_calls:
            entry = _score_ticker_at_quarter(
                ticker,
                q,
                ttrees,
                book_id,
                allow_empty=True,
                event_name=cue_names.get(q) or None,
            )
            if entry is not None:
                entries.append(entry)

    return entries


def _score_ticker_at_quarter(
    ticker: str,
    q: str,
    trees: list[dict],
    book_id: str,
    *,
    allow_empty: bool = False,
    event_name: str | None = None,
) -> dict[str, Any] | None:
    """
    Compute delivery + engagement scores for `ticker` at call `q`.

    `q` is the raw call id (``FY2026-Q2`` or ``CONF-2025-08-27``).
    Delivery rolling math still uses the canonical FY key.
    Returns None if the call has no meaningful data unless *allow_empty*.
    """
    q_key = fiscal_key(q)
    kind = period_kind(q)

    # ------------------------------------------------------------------ #
    # Delivery score — rolling rate up to and including Q               #
    #                                                                    #
    # Five failure paths contribute to the effective denominator:       #
    #   1. Explicit terminal node: delivered/hit           → confirmed  #
    #   2. Explicit terminal node: missed/dropped/…        → full miss  #
    #   3. Root delivery=="expired" OR age > HORIZON_QTRS  → full miss  #
    #   4. Open tree with ≥1 deferred node at or before Q  → 0.5 miss  #
    #   5. current_kind softer than original kind           → 0.3 miss  #
    # ------------------------------------------------------------------ #
    n_confirmed = 0
    n_failed = 0
    n_withdrawn = 0
    n_failed_frac: float = 0.0   # accumulates fractional penalties

    for t in trees:
        terminal_edge = None
        for n in (t.get("nodes") or []):
            if n["edge"] in ALL_TERMINAL_EDGES and fiscal_key(n["fiscal_period"]) <= q_key:
                terminal_edge = n["edge"]

        # Path 3a — hard expire from tree root
        if terminal_edge is None and t.get("delivery") == "expired":
            expire_key = fiscal_key(t.get("expire") or "")
            if expire_key != (0, 0) and expire_key <= q_key:
                terminal_edge = "expired"

        # Settle explicit terminal edges
        if terminal_edge in {"delivered", "hit"}:
            n_confirmed += 1
            continue
        if terminal_edge in {"missed", "dropped", "abandoned", "expired"}:
            n_failed += 1
            if terminal_edge == "abandoned":
                n_withdrawn += 1
            continue

        # From here: tree is still open at Q — apply fractional penalties
        seed_key = fiscal_key(t["seed"]["fiscal_period"])
        age = (q_key[0] - seed_key[0]) * 4 + (q_key[1] - seed_key[1])

        # Path 3b — implicit horizon: open >8 quarters = full soft miss
        if age > HORIZON_QTRS:
            n_failed_frac += 1.0
            continue

        # Path 4 — deferred: any deferred node at or before Q → 0.5 miss
        was_deferred = any(
            n["edge"] == "deferred" and fiscal_key(n["fiscal_period"]) <= q_key
            for n in (t.get("nodes") or [])
        )
        if was_deferred:
            n_failed_frac += 0.5

        # Path 5 — scope walk-back: current_kind softer than original kind → 0.3 miss
        orig_rank = _kind_rank(t.get("kind", ""))
        curr_rank = _kind_rank(t.get("current_kind", t.get("kind", "")))
        if curr_rank >= 0 and orig_rank >= 0 and curr_rank < orig_rank:
            n_failed_frac += 0.3

    n_aged = n_confirmed + n_failed
    n_aged_effective = n_confirmed + n_failed + n_failed_frac
    delivery_score: float | None = (
        n_confirmed / n_aged_effective if n_aged_effective > 0 else None
    )

    # ------------------------------------------------------------------ #
    # Engagement score — signals from this specific quarter Q            #
    # ------------------------------------------------------------------ #
    # open_trees_at_Q = seeded before Q, not yet terminally settled as of Q-1
    prev_q_key = _prev_quarter_key(q_key)

    open_trees_at_q: list[dict] = []
    for t in trees:
        seed_fp = str((t.get("seed") or {}).get("fiscal_period") or "")
        if not seed_before_call(seed_fp, q):
            continue
        # Check if it was already terminated BEFORE this call
        terminal_before_q = any(
            n["edge"] in ALL_TERMINAL_EDGES
            and (
                (period_kind(q) == "conf" and seed_before_call(str(n.get("fiscal_period") or ""), q))
                or (period_kind(q) != "conf" and fiscal_key(n["fiscal_period"]) < q_key)
            )
            for n in (t.get("nodes") or [])
        )
        if not terminal_before_q:
            open_trees_at_q.append(t)

    # New seeds introduced AT this exact call (FY or CONF), not the collapsed quarter
    new_seed_trees = [
        t for t in trees
        if str((t.get("seed") or {}).get("fiscal_period") or "").strip() == q
    ]
    n_new_seeds = len(new_seed_trees)

    # Categorise each open tree's signal AT Q
    n_restated = 0
    n_deferred = 0
    n_dropped_at_q = 0
    n_has_node_at_q = 0

    for t in open_trees_at_q:
        node_at_q = next(
            (
                n for n in (t.get("nodes") or [])
                if str(n.get("fiscal_period") or "").strip() == q
            ),
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

    # ------------------------------------------------------------------ #
    # Transparency score [0, 1]                                          #
    #                                                                    #
    # "What fraction of management's stated open commitments did they   #
    #  actually address this call?"                                      #
    #                                                                    #
    # coverage  = n_touched / open_trees  (primary driver)             #
    # quality   = (new_seeds + restatements) / (open + new_seeds)       #
    # transparency = coverage * 0.7 + quality * 0.3, clamped to [0,1]  #
    # ------------------------------------------------------------------ #
    n_touched = n_has_node_at_q           # trees with any node at Q
    coverage = n_touched / max(1, len(open_trees_at_q))
    quality = (n_new_seeds + n_restated) / max(1, len(open_trees_at_q) + n_new_seeds)
    transparency_score = min(1.0, coverage * 0.7 + quality * 0.3)

    # Skip calls with zero information unless this is a backfilled FY / CONF row
    if len(open_trees_at_q) == 0 and n_new_seeds == 0 and not allow_empty:
        return None

    return {
        "ticker": ticker,
        "fiscal_period": q,
        "period_kind": kind,
        "event_name": event_name,
        "book_id": book_id,
        # Delivery
        "delivery_score": round(delivery_score, 4) if delivery_score is not None else None,
        "n_confirmed": n_confirmed,
        "n_failed": n_failed,
        "n_failed_frac": round(n_failed_frac, 4),
        "n_withdrawn": n_withdrawn,
        "n_aged": n_aged,
        # Transparency (replaces engagement)
        "transparency_score": round(transparency_score, 4),
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
        overlay_key = BOOK_OVERLAY.get(book_id)
        if overlay_key:
            book = _merge_overlay_trees(book, overlay_key)
        entries = _scorecard_for_book(book, book_id)
        all_entries.extend(entries)
        tickers = sorted({e["ticker"] for e in entries})
        print(
            f"[scorecard] {book_id}: {len(entries)} entries, "
            f"{len(tickers)} tickers: {tickers}",
            file=sys.stderr,
        )

    # Sort: book_id, ticker, fiscal_period
    all_entries.sort(key=lambda e: (e["book_id"], e["ticker"], period_sort_key(e["fiscal_period"])))

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
