"""Preview object-matched novelty hits for the depth cohort.

Does not insert trees. Does not type delivered, hit, or missed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_trees_v2 import fiscal_key  # noqa: E402
OUT = ROOT / "Structured Narrative" / "output"

COHORT = (
    {
        "tree_id": "msft-build-analyst-briefing",
        "ticker": "MSFT",
        "book": "desk_ops_v2",
        "kind": "promise",
        "clock": "FY2017-Q4",
        "seed": "FY2017-Q2",
        "objects": ("BUILD", "financial analyst briefing"),
        "tight": ("BUILD", "analyst briefing"),
    },
    {
        "tree_id": "crm-20b-next-goal",
        "ticker": "CRM",
        "book": "desk_ops_v2",
        "kind": "goal",
        "clock": None,
        "seed": "FY2017-Q3",
        "objects": ("$20 billion", "20 billion"),
        "tight": ("$20 billion", "20 billion"),
    },
    {
        "tree_id": "lly-dividend-december",
        "ticker": "LLY",
        "book": "desk_hc_v2",
        "kind": "promise",
        "clock": "FY2016-Q4",
        "seed": "FY2016-Q2",
        "objects": ("dividend",),
        "tight": ("dividend increase", "increase the dividend", "raised the dividend"),
    },
    {
        "tree_id": "isrg-davinci-x",
        "ticker": "ISRG",
        "book": "desk_hc_v2",
        "kind": "promise",
        "clock": "FY2017-Q4",
        "seed": "FY2017-Q1",
        "objects": ("da Vinci X",),
        "tight": ("da Vinci X",),
    },
)


def load_novelty(ticker: str) -> dict:
    path = OUT / ticker / "json" / "novelty_view.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_book_tree(book_id: str, tree_id: str) -> dict | None:
    name = {
        "desk_ops_v2": "desk_trees_ops_v2.json",
        "desk_hc_v2": "desk_trees_hc_v2.json",
    }[book_id]
    payload = json.loads((OUT / "cross_company" / "json" / name).read_text(encoding="utf-8"))
    for tree in payload.get("trees") or []:
        if tree.get("tree_id") == tree_id:
            return tree
    return None


def evidence_rows(quarter: dict) -> list[dict]:
    rows: list[dict] = []
    for novelty in quarter.get("novelties") or []:
        if not isinstance(novelty, dict):
            continue
        for item in novelty.get("evidence") or []:
            if not isinstance(item, dict) or not item.get("verified"):
                continue
            rows.append(
                {
                    "fiscal_period": quarter.get("fiscal_period"),
                    "dimension": novelty.get("dimension"),
                    "status": item.get("status"),
                    "excerpt": str(item.get("excerpt") or "").replace("\n", " ").strip(),
                    "claim": str(item.get("claim") or "").strip(),
                }
            )
    return rows


def contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in tokens)


def main() -> int:
    report: list[dict] = []
    for item in COHORT:
        novelty = load_novelty(item["ticker"])
        book_tree = load_book_tree(item["book"], item["tree_id"]) or {}
        seed_key = fiscal_key(item["seed"])
        periods = [
            str(quarter.get("fiscal_period") or "")
            for quarter in novelty.get("quarters") or []
        ]
        after = [period for period in periods if fiscal_key(period) > seed_key]
        hits: list[dict] = []
        tight_hits: list[dict] = []
        for quarter in novelty.get("quarters") or []:
            fiscal = str(quarter.get("fiscal_period") or "")
            if fiscal_key(fiscal) <= seed_key:
                continue
            for row in evidence_rows(quarter):
                blob = f"{row['excerpt']} {row['claim']}"
                if contains_any(blob, item["objects"]):
                    hits.append(row)
                if contains_any(blob, item["tight"]):
                    tight_hits.append(row)
        nodes = book_tree.get("nodes") or []
        report.append(
            {
                "tree_id": item["tree_id"],
                "ticker": item["ticker"],
                "book": item["book"],
                "kind": item["kind"],
                "seed": item["seed"],
                "clock": item["clock"],
                "novelty_quarters": len(periods),
                "quarters_after_seed": len(after),
                "first_after": after[0] if after else None,
                "last_after": after[-1] if after else None,
                "book_nodes": [
                    {
                        "fiscal_period": node.get("fiscal_period"),
                        "edge": node.get("edge"),
                        "excerpt": node.get("excerpt"),
                    }
                    for node in nodes
                ],
                "book_state": book_tree.get("state"),
                "book_slipped": book_tree.get("slipped"),
                "object_hits": len(hits),
                "tight_hits": len(tight_hits),
                "tight_preview": tight_hits[:8],
                "object_preview": hits[:6],
            }
        )
    dest = ROOT / "data" / "desk_depth_cohort_pause.json"
    dest.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for row in report:
        print(
            f"{row['tree_id']} {row['ticker']} after={row['quarters_after_seed']} "
            f"object={row['object_hits']} tight={row['tight_hits']} "
            f"book_nodes={len(row['book_nodes'])} state={row['book_state']} "
            f"slipped={row['book_slipped']}"
        )
        for hit in row["tight_preview"][:4]:
            print(f"  {hit['fiscal_period']} {hit['dimension']} {hit['excerpt'][:220]}")
        print()
    print(f"wrote {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
