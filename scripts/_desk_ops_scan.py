"""Scan scored tech novelty_views into per-ticker cue queues.

Does not insert trees. Does not call an LLM. Does not read transcripts_raw.
Does not rewrite NVIDIA gold.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_cue_proposals import write_cue_proposals  # noqa: E402
from scripts._desk_cue_queue import write_cue_queue  # noqa: E402
from scripts._desk_trees_v2_ops import (  # noqa: E402
    OPS_STAMP,
    TECH_TICKERS,
    load_novelty_map,
    novelty_path_for,
    ops_book_path,
)
from scripts._desk_trees_v2_recall import novelty_periods  # noqa: E402


def _latest(novelty: dict) -> str:
    periods = novelty_periods(novelty)
    return periods[-1] if periods else ""


def main() -> int:
    now = datetime.now(timezone.utc)
    novelty_by = load_novelty_map(TECH_TICKERS, ROOT)
    ops_path = ops_book_path(ROOT)
    ops = {}
    if ops_path.is_file():
        ops = json.loads(ops_path.read_text(encoding="utf-8"))
    trees = list(ops.get("trees") or []) if str(ops.get("generated_at") or "") == OPS_STAMP else []
    rows: list[dict[str, object]] = []
    for ticker in TECH_TICKERS:
        novelty = novelty_by.get(ticker)
        if novelty is None:
            rows.append({"ticker": ticker, "status": "skipped", "reason": "no_novelty_view"})
            continue
        if ticker == "NVDA":
            rows.append({"ticker": ticker, "status": "gold", "note": "use desk_cue_queue_v2.json"})
            continue
        ticker_trees = [
            tree
            for tree in trees
            if str(tree.get("ticker") or "").upper() == ticker
        ]
        book = {
            "generated_at": OPS_STAMP,
            "book_id": "desk_ops_v2",
            "trees": ticker_trees,
        }
        written = write_cue_queue(
            repo_root=ROOT,
            book=book,
            novelty=novelty,
            trees=ticker_trees,
            latest_quarter=_latest(novelty),
            now=now,
            ticker=ticker,
        )
        proposals = write_cue_proposals(
            repo_root=ROOT,
            book=book,
            queue=written,
            now=now,
            ticker=ticker,
        )
        rows.append(
            {
                "ticker": ticker,
                "status": "written",
                "n_seedable": written.get("n_seedable"),
                "n_covered": written.get("n_covered"),
                "n_missed": written.get("n_missed"),
                "n_proposals": proposals.get("n_proposals"),
                "latest": written.get("latest_quarter"),
            }
        )
    index = {
        "generated_at": OPS_STAMP,
        "written_at": now.isoformat(),
        "n_tickers": len(rows),
        "rows": rows,
    }
    index_path = (
        ROOT
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_cue_queue_ops_v2.json"
    )
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(json.dumps(index, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
