"""Build the management-regime sidecar.

Writes ``Structured Narrative/output/cross_company/json/desk_regimes_v1.json``.

Does not call Snowflake.  Reads:
  - config/management_regimes.json
  - The three book JSONs via claims_trees.py loaders
  - The three cue-queue JSONs (for latest_scored_fiscal)

The stamp constant ``REGIMES_STAMP`` is bumped whenever the sidecar schema or
logic changes; the loader in ``claims_regimes.py`` checks it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_regimes import (  # noqa: E402
    build_transfer_ledger,
    load_management_regimes,
    regime_rate_counts,
    split_trees_by_regime,
    transfer_kind,
)
from services.earnings_monitor.dashboard.claims_trees import (  # noqa: E402
    _BOOK_HC,
    _BOOK_NVDA,
    _BOOK_OPS,
    latest_scored_fiscal,
    load_desk_cue_queue_hc_v2,
    load_desk_cue_queue_ops_v2,
    load_desk_cue_queue_v2,
    load_desk_trees_hc_v2,
    load_desk_trees_ops_v2,
    load_desk_trees_v2,
)

REGIMES_STAMP = "2026-09-01T16:00:00+00:00"
REGIMES_FILENAME = "desk_regimes_v1.json"
CAPTION = (
    "Management-regime tracking. Each tree is attributed to the regime "
    "under which it was seeded (seed.fiscal_period). Trees that cross a CEO "
    "transition are classified by transfer_kind: prior_closed, inherited_adopted, "
    "inherited_closed_by_successor, inherited_overdue, or inherited_ignored."
)


def sidecar_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else ROOT
    return (
        root
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / REGIMES_FILENAME
    )


def _transfer_kind_summary(trees: Sequence[Mapping[str, Any]], regimes: list[dict]) -> dict[str, int]:
    """Count trees by transfer_kind for a collection."""
    counts: dict[str, int] = {}
    for tree in trees:
        k = transfer_kind(tree, regimes)
        counts[k] = counts.get(k, 0) + 1
    return counts


def build_book_block(
    book_id: str,
    payload: Mapping[str, Any] | None,
    queue: Mapping[str, Any] | None,
    regimes: list[dict],
) -> dict[str, Any] | None:
    """Compute regime analytics for a single book.

    Returns a dict suitable for the ``books`` block of the sidecar, or ``None``
    if the book payload is not available.
    """
    if payload is None:
        return None

    trees = [t for t in (payload.get("trees") or []) if isinstance(t, Mapping)]
    latest = latest_scored_fiscal(payload, queue)

    # Per-regime rate counts (known-delivered + settled share per CEO)
    raw_rates = regime_rate_counts(trees, regimes, latest)
    buckets = split_trees_by_regime(trees, regimes)

    regime_rates: dict[str, dict] = {}
    for regime_id, counts in raw_rates.items():
        bucket_trees = buckets.get(regime_id) or []
        transfer_summary = _transfer_kind_summary(bucket_trees, regimes)
        regime_rates[regime_id] = {
            "n_trees": len(bucket_trees),
            "known_delivered_counts": counts,
            "transfer_kind_summary": transfer_summary,
        }

    # Full transfer ledger for this book
    ledger = build_transfer_ledger(trees, regimes)

    return {
        "book_id": book_id,
        "as_of": latest,
        "n_trees": len(trees),
        "regime_rates": regime_rates,
        "transfer_ledger": ledger,
    }


def build_sidecar(
    *,
    repo_root: Path | str | None = None,
    history_source: str | Path | None = None,
    regimes_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build and return the full regimes sidecar dict."""
    root = Path(repo_root) if repo_root is not None else ROOT
    regimes = load_management_regimes(regimes_path)

    gold = load_desk_trees_v2(history_source)
    ops = load_desk_trees_ops_v2(history_source)
    healthcare = load_desk_trees_hc_v2(history_source)

    books: dict[str, Any] = {}
    for book_id, payload, queue in (
        (_BOOK_NVDA, gold, load_desk_cue_queue_v2(history_source)),
        (_BOOK_OPS, ops, load_desk_cue_queue_ops_v2(history_source)),
        (_BOOK_HC, healthcare, load_desk_cue_queue_hc_v2(history_source)),
    ):
        block = build_book_block(book_id, payload, queue, regimes)
        if block is not None:
            books[book_id] = block

    return {
        "generated_at": REGIMES_STAMP,
        "caption": CAPTION,
        "regimes": regimes,
        "books": books,
    }


def write_sidecar(
    *,
    repo_root: Path | str | None = None,
    history_source: str | Path | None = None,
    regimes_path: str | Path | None = None,
) -> Path:
    """Write the sidecar to disk and return its path."""
    root = Path(repo_root) if repo_root is not None else ROOT
    path = sidecar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_sidecar(
        repo_root=root,
        history_source=history_source,
        regimes_path=regimes_path,
    )
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def main() -> int:
    path = write_sidecar(repo_root=ROOT)
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary: dict[str, Any] = {
        "path": str(path),
        "n_regimes": len(payload.get("regimes") or []),
        "books": {},
    }
    for book_id, block in (payload.get("books") or {}).items():
        ledger = block.get("transfer_ledger") or []
        from collections import Counter
        kind_counter = Counter(e.get("transfer_kind") for e in ledger)
        summary["books"][book_id] = {
            "as_of": block.get("as_of"),
            "n_trees": block.get("n_trees"),
            "n_regime_buckets": len(block.get("regime_rates") or {}),
            "transfer_ledger_size": len(ledger),
            "transfer_kinds": dict(kind_counter),
        }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
