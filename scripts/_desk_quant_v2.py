"""Build the quant / expire sidecar from trees and local IBES parquet.

Does not rewrite gold. Does not call Snowflake. Does not write production_v1.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_trees_v2 import fiscal_key  # noqa: E402
from services.earnings_monitor.dashboard.claims_quant import (  # noqa: E402
    QUANT_FILENAME,
    QUANT_STAMP,
    quant_verdict,
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

CAPTION = (
    "Quant cross-check. Clocked trees check at the clock. Unclocked trees "
    "wait four silent quarters, then stop at expire or seed+8Q. A missing "
    "actual is expired, not a miss. Not desk_trust."
)


def sidecar_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else ROOT
    return (
        root
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / QUANT_FILENAME
    )


def narrative_quant_path(ticker: str, repo_root: Path) -> Path:
    return (
        repo_root
        / "Structured Narrative"
        / "output"
        / str(ticker).upper()
        / "parquet"
        / "narrative_quant.parquet"
    )


def load_actuals(ticker: str, repo_root: Path) -> list[dict[str, Any]]:
    path = narrative_quant_path(ticker, repo_root)
    if not path.is_file():
        return []
    try:
        import pandas as pd
    except ImportError:
        return []
    try:
        frame = pd.read_parquet(path)
    except (OSError, ValueError, TypeError):
        return []
    if frame is None or frame.empty:
        return []
    keep = [col for col in ("measure", "fiscal_period", "actual_value", "period_role") if col in frame.columns]
    if not keep:
        return []
    return frame[keep].to_dict(orient="records")


def ticker_as_of(
    ticker: str,
    *,
    repo_root: Path,
    book_as_of: str | None,
    actuals: Sequence[Mapping[str, Any]],
) -> str | None:
    """Use that company's last scored quarter, not the book-wide max."""
    path = (
        repo_root
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / f"desk_cue_queue_v2_{ticker}.json"
    )
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            payload = None
        if isinstance(payload, dict):
            latest = str(payload.get("latest_quarter") or "").strip() or None
            if latest:
                return latest
    fiscals = [
        str(row.get("fiscal_period") or "")
        for row in actuals
        if fiscal_key(str(row.get("fiscal_period") or ""))[0] >= 0
    ]
    if fiscals:
        return max(fiscals, key=lambda period: fiscal_key(period))
    return book_as_of


def wants_row(tree: Mapping[str, Any]) -> bool:
    return bool(tree.get("quant") or tree.get("expire"))


def build_book_block(
    book_id: str,
    payload: Mapping[str, Any] | None,
    queue: Mapping[str, Any] | None,
    repo_root: Path,
) -> dict[str, Any] | None:
    if payload is None:
        return None
    trees = [tree for tree in (payload.get("trees") or []) if isinstance(tree, Mapping)]
    as_of = latest_scored_fiscal(payload, queue)
    cache: dict[str, list[dict[str, Any]]] = {}
    rows: list[dict[str, Any]] = []
    for tree in trees:
        if not wants_row(tree):
            continue
        ticker = str(tree.get("ticker") or "").upper()
        if ticker not in cache:
            cache[ticker] = load_actuals(ticker, repo_root)
        actuals = cache.get(ticker) or []
        rows.append(
            quant_verdict(
                tree,
                as_of=ticker_as_of(
                    ticker,
                    repo_root=repo_root,
                    book_as_of=as_of,
                    actuals=actuals,
                ),
                actuals=actuals,
            )
        )
    return {
        "book_id": book_id,
        "as_of": as_of,
        "n_rows": len(rows),
        "rows": rows,
    }


def build_sidecar(
    *,
    repo_root: Path | str | None = None,
    history_source: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(repo_root) if repo_root is not None else ROOT
    gold = load_desk_trees_v2(history_source)
    ops = load_desk_trees_ops_v2(history_source)
    healthcare = load_desk_trees_hc_v2(history_source)
    books: dict[str, Any] = {}
    for book_id, payload, queue in (
        (_BOOK_NVDA, gold, load_desk_cue_queue_v2(history_source)),
        (_BOOK_OPS, ops, load_desk_cue_queue_ops_v2(history_source)),
        (_BOOK_HC, healthcare, load_desk_cue_queue_hc_v2(history_source)),
    ):
        block = build_book_block(book_id, payload, queue, root)
        if block is not None:
            books[book_id] = block
    return {
        "generated_at": QUANT_STAMP,
        "caption": CAPTION,
        "books": books,
    }


def write_sidecar(
    *,
    repo_root: Path | str | None = None,
    history_source: str | Path | None = None,
) -> Path:
    root = Path(repo_root) if repo_root is not None else ROOT
    path = sidecar_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_sidecar(repo_root=root, history_source=history_source), indent=2),
        encoding="utf-8",
    )
    return path


def main() -> int:
    path = write_sidecar(repo_root=ROOT)
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = {
        "path": str(path),
        "books": {
            name: {
                "as_of": block.get("as_of"),
                "n_rows": block.get("n_rows"),
                "verdicts": dict(
                    Counter(str(row.get("verdict")) for row in (block.get("rows") or []))
                ),
            }
            for name, block in (payload.get("books") or {}).items()
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
