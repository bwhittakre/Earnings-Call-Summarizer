"""Management-regime inference and analytics.

Pure functions: no Streamlit, no Snowflake.  Importable by the Roz renderer,
the sidecar builder, Rank IC, and the Dimension panel.

Regime lifecycle
----------------
A *regime* is one person's continuous tenure in one executive role at one
company.  The catalog (``config/management_regimes.json``) records every known
CEO tenure for every tracked ticker, using the company's own fiscal labels.

``start_fiscal`` / ``end_fiscal`` are the *first* / *last* scored earnings call
under that person — not the hire / departure calendar date.  ``end_fiscal=null``
means still in seat.

Cite-transfer taxonomy
----------------------
When a tree is seeded under one regime but outlives a regime boundary it is
classified with ``transfer_kind()``.  Six possible statuses:

    single_regime             — seed and all activity in one regime; no boundary crossed
    prior_closed              — scored terminal *before* the transition; no issue
    inherited_adopted         — open at transition; new regime has ≥1 non-silent node
    inherited_closed_by_successor — open at transition; new regime provided the terminal
    inherited_overdue         — open at transition; no new-regime cite; clock is due
    inherited_ignored         — open at transition; no new-regime cite; clock not yet due
"""

from __future__ import annotations

import json
import pathlib
from collections.abc import Mapping, Sequence
from typing import Any

from scripts._desk_trees_v2 import (
    clock_is_due,
    fiscal_key,
    known_delivered_counts,
    PROMISE_TERMINAL,
    GOAL_TERMINAL,
)

_DEFAULT_CATALOG = (
    pathlib.Path(__file__).resolve().parent.parent / "config" / "management_regimes.json"
)

# ─────────────────────────────────────────────────────────────────────────────
# I/O helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_management_regimes(path: str | pathlib.Path | None = None) -> list[dict]:
    """Load the regime catalog from disk.

    Returns an empty list if the file is missing (so callers can safely degrade).
    """
    p = pathlib.Path(path) if path else _DEFAULT_CATALOG
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            return raw
        return []
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Core lookup helpers
# ─────────────────────────────────────────────────────────────────────────────

def regimes_for_ticker(ticker: str, regimes: list[dict]) -> list[dict]:
    """All regime entries for *ticker*, sorted ascending by start_fiscal."""
    matches = [r for r in regimes if (r.get("ticker") or "").upper() == ticker.upper()]
    return sorted(matches, key=lambda r: fiscal_key(r.get("start_fiscal") or ""))


def regime_for_fiscal(
    ticker: str, fiscal: str, regimes: list[dict]
) -> dict | None:
    """Return the regime active at *fiscal* for *ticker*.

    A regime covers ``start_fiscal <= fiscal`` and either
    ``fiscal <= end_fiscal`` or ``end_fiscal is null`` (still in seat).
    Returns ``None`` when no entry covers the requested fiscal.
    """
    fkey = fiscal_key(fiscal)
    if fkey[0] < 0:
        return None
    for regime in regimes_for_ticker(ticker, regimes):
        start = fiscal_key(regime.get("start_fiscal") or "")
        if start[0] < 0 or fkey < start:
            continue
        end_raw = regime.get("end_fiscal")
        if end_raw is None:
            return regime  # open-ended; still in seat
        end = fiscal_key(end_raw)
        if fkey <= end:
            return regime
    return None


def regime_for_tree(tree: Mapping[str, Any], regimes: list[dict]) -> dict | None:
    """Convenience wrapper: look up the regime for a tree by its seed fiscal."""
    ticker = str(tree.get("ticker") or "")
    fiscal = str((tree.get("seed") or {}).get("fiscal_period") or "")
    return regime_for_fiscal(ticker, fiscal, regimes)


def current_regime(ticker: str, regimes: list[dict]) -> dict | None:
    """Return the open-ended (``end_fiscal=null``) regime for *ticker*."""
    for regime in regimes_for_ticker(ticker, regimes):
        if regime.get("end_fiscal") is None:
            return regime
    return None


def transition_fiscals(ticker: str, regimes: list[dict]) -> list[str]:
    """Return the ``start_fiscal`` of every *non-first* regime for *ticker*.

    These are the fiscal periods at which CEO accountability changes.
    """
    ordered = regimes_for_ticker(ticker, regimes)
    if len(ordered) < 2:
        return []
    return [r["start_fiscal"] for r in ordered[1:]]


# ─────────────────────────────────────────────────────────────────────────────
# Tree-level helpers
# ─────────────────────────────────────────────────────────────────────────────

def _first_terminal_fiscal(tree: Mapping[str, Any]) -> str | None:
    """Return the fiscal_period of the earliest terminal node in *tree*.

    A terminal node is one whose edge is in PROMISE_TERMINAL ∪ GOAL_TERMINAL.
    Returns ``None`` if no terminal node exists (tree still open).
    """
    terminal_edges = set(PROMISE_TERMINAL) | set(GOAL_TERMINAL)
    candidates: list[str] = []
    for node in tree.get("nodes") or []:
        if str(node.get("edge") or "") in terminal_edges:
            fp = str(node.get("fiscal_period") or "")
            if fiscal_key(fp)[0] >= 0:
                candidates.append(fp)
    if not candidates:
        return None
    return min(candidates, key=fiscal_key)


def _has_post_transition_non_silent(
    tree: Mapping[str, Any], transition_key: tuple[int, int]
) -> bool:
    """True if the tree has ≥1 node at or after *transition_key* with a
    non-'silent' edge."""
    for node in tree.get("nodes") or []:
        fp = str(node.get("fiscal_period") or "")
        if fiscal_key(fp) >= transition_key and str(node.get("edge") or "") != "silent":
            return True
    return False


def transfer_kind(tree: Mapping[str, Any], regimes: list[dict]) -> str:
    """Classify how a tree is handled across a management regime boundary.

    Returns one of:
        single_regime
        prior_closed
        inherited_adopted
        inherited_closed_by_successor
        inherited_overdue
        inherited_ignored
    """
    ticker = str(tree.get("ticker") or "")
    transitions = transition_fiscals(ticker, regimes)
    seed_key = fiscal_key(str((tree.get("seed") or {}).get("fiscal_period") or ""))
    is_open = bool(tree.get("open"))

    for t_fiscal in transitions:
        t_key = fiscal_key(t_fiscal)
        if seed_key >= t_key:
            continue  # tree was seeded *after* this transition; keep looking
        # This transition applies: tree was seeded in the prior regime
        if not is_open:
            terminal_fp = _first_terminal_fiscal(tree)
            if terminal_fp is None:
                return "prior_closed"  # defensive fallback
            if fiscal_key(terminal_fp) < t_key:
                return "prior_closed"
            return "inherited_closed_by_successor"
        # Tree is still open at this transition
        if _has_post_transition_non_silent(tree, t_key):
            return "inherited_adopted"
        # No post-transition activity: check clock
        clock = str(tree.get("clock") or "") or None
        expire = str(tree.get("expire") or "") or None
        clock_due = (
            (clock and clock_is_due(clock, t_fiscal))
            or (expire and clock_is_due(expire, t_fiscal))
        )
        if clock_due:
            return "inherited_overdue"
        return "inherited_ignored"

    return "single_regime"


# ─────────────────────────────────────────────────────────────────────────────
# Aggregate helpers
# ─────────────────────────────────────────────────────────────────────────────

def split_trees_by_regime(
    trees: Sequence[Mapping[str, Any]], regimes: list[dict]
) -> dict[str, list[dict]]:
    """Partition trees by the regime under which they were *seeded*.

    Returns ``{regime_id: [trees]}``.  Trees whose seed fiscal maps to no
    known regime are placed under the key ``"unknown"``.
    """
    result: dict[str, list[dict]] = {}
    for tree in trees:
        regime = regime_for_tree(tree, regimes)
        key = regime["regime_id"] if regime else "unknown"
        result.setdefault(key, []).append(dict(tree))
    return result


def regime_rate_counts(
    trees: Sequence[Mapping[str, Any]],
    regimes: list[dict],
    latest: str,
) -> dict[str, dict]:
    """Compute known-delivered counts for each regime bucket.

    Returns ``{regime_id: known_delivered_counts(...)}``.

    Only trees *seeded* under a given regime contribute to that regime's
    numerator.  Inherited trees (seeded under a prior regime but still open
    at a transition) are counted under their seed regime unless the caller
    explicitly wants a different attribution — the point is accountability for
    what was *promised* under that leadership.
    """
    buckets = split_trees_by_regime(trees, regimes)
    return {
        regime_id: known_delivered_counts(bucket_trees, latest)
        for regime_id, bucket_trees in buckets.items()
    }


# ─────────────────────────────────────────────────────────────────────────────
# Transfer-ledger helper
# ─────────────────────────────────────────────────────────────────────────────

def build_transfer_ledger(
    trees: Sequence[Mapping[str, Any]], regimes: list[dict]
) -> list[dict]:
    """Return a list of dicts describing every tree that crosses a regime boundary.

    Only trees where ``transfer_kind != 'single_regime'`` are included.
    """
    ledger: list[dict] = []
    for tree in trees:
        kind = transfer_kind(tree, regimes)
        if kind == "single_regime":
            continue
        ticker = str(tree.get("ticker") or "")
        seed_fp = str((tree.get("seed") or {}).get("fiscal_period") or "")
        seed_regime = regime_for_fiscal(ticker, seed_fp, regimes)

        # Find the first transition that applies
        trans_fiscal: str | None = None
        for t_fp in transition_fiscals(ticker, regimes):
            if fiscal_key(seed_fp) < fiscal_key(t_fp):
                trans_fiscal = t_fp
                break

        ledger.append(
            {
                "tree_id": tree.get("tree_id"),
                "ticker": ticker,
                "title": tree.get("title"),
                "seed_regime": seed_regime["regime_id"] if seed_regime else None,
                "seed_regime_person": seed_regime["named_person"] if seed_regime else None,
                "transfer_kind": kind,
                "seed_fiscal": seed_fp,
                "transition_fiscal": trans_fiscal,
                "clock": tree.get("clock"),
                "delivery": tree.get("delivery"),
                "open": tree.get("open"),
            }
        )
    return ledger
