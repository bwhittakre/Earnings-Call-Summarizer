"""Read-only want→will candidates. Does not insert trees. No LLM."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_trees_v2 import BECAME_PROMISE, fiscal_key  # noqa: E402
from scripts._desk_trees_v2_hc import HC_TICKERS, hc_book_path  # noqa: E402
from scripts._desk_trees_v2_ops import TECH_TICKERS, load_novelty_map, ops_book_path  # noqa: E402
from scripts._desk_trees_v2_recall import (  # noqa: E402
    classify,
    collect_candidates,
    novelty_periods,
)

STOP = frozenset(
    {
        "about",
        "after",
        "billion",
        "million",
        "quarter",
        "revenue",
        "their",
        "there",
        "these",
        "those",
        "which",
        "while",
        "would",
        "could",
        "should",
        "expect",
        "believe",
        "target",
        "growth",
        "going",
        "want",
        "will",
        "this",
        "that",
        "with",
        "from",
        "have",
        "been",
        "were",
        "into",
        "over",
        "more",
        "than",
        "year",
        "next",
    }
)
OUT = ROOT / "data" / "desk_harden_candidates.json"


def object_tokens(objects: Sequence[object], excerpt: str = "") -> list[str]:
    found: list[str] = []
    for token in objects:
        text = str(token or "").strip()
        if text:
            found.append(text)
    if found:
        return found
    for word in str(excerpt or "").replace("$", "").split():
        cleaned = "".join(ch for ch in word if ch.isalnum() or ch == "%")
        if len(cleaned) >= 5 and cleaned.lower() not in STOP:
            found.append(cleaned)
    return found[:8]


def excerpt_has_object(excerpt: str, objects: Sequence[str]) -> list[str]:
    lowered = excerpt.lower()
    return [token for token in objects if token.lower() in lowered]


def later_promise_hits(
    novelty: Mapping[str, object],
    *,
    ticker: str,
    after_fiscal: str,
    objects: Sequence[str],
) -> list[dict[str, object]]:
    periods = [
        period
        for period in novelty_periods(novelty)
        if fiscal_key(period) > fiscal_key(after_fiscal)
    ]
    hits: list[dict[str, object]] = []
    for row in collect_candidates(novelty, periods, ticker=ticker):
        if row.get("class") != "promise":
            continue
        excerpt = str(row.get("excerpt") or "")
        matched = excerpt_has_object(excerpt, objects)
        if not matched:
            continue
        hits.append(
            {
                "fiscal_period": row.get("fiscal_period"),
                "dimension": row.get("dimension"),
                "status": row.get("status"),
                "excerpt": excerpt,
                "objects": matched,
            }
        )
    hits.sort(key=lambda item: fiscal_key(str(item.get("fiscal_period") or "")))
    return hits


def candidates_for_trees(
    trees: Sequence[Mapping[str, object]],
    novelty_by: Mapping[str, Mapping[str, object] | None],
    *,
    book: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for tree in trees:
        if str(tree.get("kind") or "") != "goal":
            continue
        if str(tree.get("goal_outcome") or "") == BECAME_PROMISE:
            continue
        ticker = str(tree.get("ticker") or "").upper()
        novelty = novelty_by.get(ticker)
        if not novelty:
            continue
        seed = tree.get("seed") or {}
        seed_fiscal = str(seed.get("fiscal_period") or "")
        objects = object_tokens(list(tree.get("objects") or []), str(seed.get("excerpt") or ""))
        hits = later_promise_hits(
            novelty, ticker=ticker, after_fiscal=seed_fiscal, objects=objects
        )
        if not hits:
            continue
        first = hits[0]
        rows.append(
            {
                "book": book,
                "source": "typed-goal",
                "ticker": ticker,
                "tree_id": tree.get("tree_id"),
                "title": tree.get("title"),
                "seed_fiscal": seed_fiscal,
                "will_fiscal": first.get("fiscal_period"),
                "objects": objects,
                "matched": first.get("objects"),
                "excerpt": first.get("excerpt"),
                "dimension": first.get("dimension"),
                "status": first.get("status"),
                "n_later_hits": len(hits),
            }
        )
    return rows


def candidates_for_leftover(
    missed: Sequence[Mapping[str, object]],
    novelty_by: Mapping[str, Mapping[str, object] | None],
    *,
    book: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for item in missed:
        if str(item.get("class") or "") != "goal":
            continue
        ticker = str(item.get("ticker") or "").upper()
        novelty = novelty_by.get(ticker)
        if not novelty:
            continue
        seed_fiscal = str(item.get("fiscal_period") or "")
        excerpt = str(item.get("excerpt") or "")
        objects = object_tokens([], excerpt)
        hits = later_promise_hits(
            novelty, ticker=ticker, after_fiscal=seed_fiscal, objects=objects
        )
        if not hits:
            continue
        first = hits[0]
        rows.append(
            {
                "book": book,
                "source": "leftover-goal",
                "ticker": ticker,
                "tree_id": None,
                "title": None,
                "seed_fiscal": seed_fiscal,
                "will_fiscal": first.get("fiscal_period"),
                "objects": objects,
                "matched": first.get("objects"),
                "excerpt": first.get("excerpt"),
                "dimension": first.get("dimension"),
                "status": first.get("status"),
                "n_later_hits": len(hits),
                "goal_excerpt": excerpt,
            }
        )
    return rows


def _queue_missed(cross: Path, tickers: Sequence[str]) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for ticker in tickers:
        path = cross / f"desk_cue_queue_v2_{ticker}.json"
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("missed") or []:
            if isinstance(row, Mapping):
                item = dict(row)
                item.setdefault("ticker", ticker)
                found.append(item)
    return found


def main() -> int:
    ops_tickers = tuple(t for t in TECH_TICKERS if t != "NVDA")
    novelty_ops = load_novelty_map(ops_tickers, ROOT)
    novelty_hc = load_novelty_map(HC_TICKERS, ROOT)
    ops_book = json.loads(ops_book_path(ROOT).read_text(encoding="utf-8"))
    hc_book = json.loads(hc_book_path(ROOT).read_text(encoding="utf-8"))
    cross = ROOT / "Structured Narrative" / "output" / "cross_company" / "json"
    typed = [
        *candidates_for_trees(ops_book.get("trees") or [], novelty_ops, book="desk_ops_v2"),
        *candidates_for_trees(hc_book.get("trees") or [], novelty_hc, book="desk_hc_v2"),
    ]
    leftover = [
        *candidates_for_leftover(
            _queue_missed(cross, ops_tickers),
            novelty_ops,
            book="desk_ops_v2",
        ),
        *candidates_for_leftover(
            _queue_missed(cross, HC_TICKERS),
            novelty_hc,
            book="desk_hc_v2",
        ),
    ]
    payload = {
        "note": "Candidates only. Do not auto-insert. Gold is not scanned.",
        "n_typed_goals": len(typed),
        "n_leftover_goals": len(leftover),
        "typed_goals": typed,
        "leftover_goals": leftover[:80],
    }
    OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(
        {
            "wrote": str(OUT),
            "n_typed_goals": len(typed),
            "n_leftover_goals": len(leftover),
            "typed_ids": [row.get("tree_id") for row in typed],
        },
        indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
