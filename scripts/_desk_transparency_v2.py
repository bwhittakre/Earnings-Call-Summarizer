"""Build the management-transparency sidecar.

Reads desk trees and novelty_view. Does not rewrite gold, ops, or
healthcare books. Does not invent delivered, hit, or missed.
Does not write production_v1 or desk_trust.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_claims_v1 import all_verified_evidence, first_object_hit  # noqa: E402
from scripts._desk_path_id_v1 import quarter_for_fiscal  # noqa: E402
from services.earnings_monitor.dashboard.claims_desk import fiscal_key  # noqa: E402
from services.earnings_monitor.dashboard.claims_trees import (  # noqa: E402
    _BOOK_HC,
    _BOOK_NVDA,
    _BOOK_OPS,
    load_desk_trees_hc_v2,
    load_desk_trees_ops_v2,
    load_desk_trees_v2,
)
from services.earnings_monitor.dashboard.claims_transparency import (  # noqa: E402
    TRANSPARENCY_FILENAME,
    TRANSPARENCY_STAMP,
    book_counts,
    collapse_ledger,
    expanding_rows,
    merge_events,
)
from services.earnings_monitor.desk_trees import novelty_view_path  # noqa: E402

CAPTION = (
    "Management transparency. After a dated clock, a later scored call "
    "that does not take up the claim is slipped. Someday wants with no "
    "clock are not implicit neglect. Withdrawn is typed dropped or "
    "abandoned. Not desk_trust."
)


def sidecar_path(repo_root: Path | str | None = None) -> Path:
    root = Path(repo_root) if repo_root is not None else ROOT
    return (
        root
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / TRANSPARENCY_FILENAME
    )


def novelty_periods(novelty_view: Mapping[str, object] | None) -> list[str]:
    if not novelty_view:
        return []
    found: list[str] = []
    quarters = novelty_view.get("quarters")
    if isinstance(quarters, dict):
        raw = quarters.keys()
    elif isinstance(quarters, list):
        raw = (
            item.get("fiscal_period")
            for item in quarters
            if isinstance(item, Mapping)
        )
    else:
        raw = ()
    for item in raw:
        period = str(item or "").strip()
        if fiscal_key(period)[0] >= 0:
            found.append(period)
    found = list(dict.fromkeys(found))
    found.sort(key=lambda period: fiscal_key(period))
    return found


def load_novelty(ticker: str, repo_root: Path) -> dict | None:
    path = novelty_view_path(repo_root, ticker)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def implicit_periods_for_tree(
    tree: Mapping[str, object],
    novelty_view: Mapping[str, object] | None,
) -> list[tuple[str, bool]]:
    objects = [str(token) for token in (tree.get("objects") or ()) if str(token).strip()]
    found: list[tuple[str, bool]] = []
    for period in novelty_periods(novelty_view):
        quarter = quarter_for_fiscal(novelty_view, period)
        if quarter is None:
            continue
        hit = first_object_hit(all_verified_evidence(quarter), objects) if objects else None
        found.append((period, hit is not None))
    return found


def events_for_book(
    trees: Sequence[Mapping[str, object]],
    novelty_by_ticker: Mapping[str, Mapping[str, object] | None],
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = []
    for tree in trees:
        if not isinstance(tree, Mapping):
            continue
        ticker = str(tree.get("ticker") or "").upper()
        events.extend(
            merge_events(tree, implicit_periods_for_tree(tree, novelty_by_ticker.get(ticker)))
        )
    return events


def company_rates(events: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    tickers = sorted({str(row.get("ticker") or "").upper() for row in events if row.get("ticker")})
    rows: list[dict[str, object]] = []
    for ticker in tickers:
        here = [row for row in events if str(row.get("ticker") or "").upper() == ticker]
        rows.append({"ticker": ticker, **book_counts(here)})
    return rows


def build_book_block(
    book_id: str,
    trees: Sequence[Mapping[str, object]],
    novelty_by_ticker: Mapping[str, Mapping[str, object] | None],
) -> dict[str, object]:
    events = events_for_book(trees, novelty_by_ticker)
    return {
        "book_id": book_id,
        "book": book_counts(events),
        "by_company": company_rates(events),
        "rows": expanding_rows(events),
        "events": events,
        "ledger": collapse_ledger(events),
    }


def build_sidecar(
    *,
    repo_root: Path | str | None = None,
    history_source: str | Path | None = None,
) -> dict[str, object]:
    root = Path(repo_root) if repo_root is not None else ROOT
    gold = load_desk_trees_v2(history_source)
    ops = load_desk_trees_ops_v2(history_source)
    healthcare = load_desk_trees_hc_v2(history_source)
    books: dict[str, object] = {}
    for book_id, payload in (
        (_BOOK_NVDA, gold),
        (_BOOK_OPS, ops),
        (_BOOK_HC, healthcare),
    ):
        if payload is None:
            continue
        trees = [tree for tree in (payload.get("trees") or []) if isinstance(tree, Mapping)]
        tickers = sorted({str(tree.get("ticker") or "").upper() for tree in trees if tree.get("ticker")})
        novelty = {ticker: load_novelty(ticker, root) for ticker in tickers}
        books[book_id] = build_book_block(book_id, trees, novelty)
    return {
        "generated_at": TRANSPARENCY_STAMP,
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
    payload = build_sidecar(repo_root=root, history_source=history_source)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def main() -> int:
    path = write_sidecar(repo_root=ROOT)
    payload = json.loads(path.read_text(encoding="utf-8"))
    summary = {
        "path": str(path),
        "books": {
            name: block.get("book")
            for name, block in (payload.get("books") or {}).items()
        },
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
