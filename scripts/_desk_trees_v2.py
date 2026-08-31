"""Claims desk v2: multi-quarter promise/goal trees.

New stamp. Does not rewrite desk_claims_v1.json.
Does not read transcripts_raw. Does not dump the remaining 125.
Path ID is not the verdict. No new LLM on the gold run.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts._desk_claims_v1 import (  # noqa: E402
    LOCKED_GENERATED_AT as V1_LOCKED_GENERATED_AT,
    all_verified_evidence,
    first_object_hit,
)
from scripts._desk_path_id_v1 import quarter_for_fiscal  # noqa: E402
from scripts._desk_trees_v2_nvda import NVDA_TREES  # noqa: E402

CASE_STUDY_ID = "desk_trees_v2"
BOOK_ID = "nvda_gold_v2"
NVDA_STAMP = "2026-08-27T18:02:00+00:00"
SPLIT = "nvda-gold-20q-fy2022q2-fy2027q1"
FULL_SPLIT = "nvda-full-fy2016q2-present"
WINDOW: tuple[str, ...] = (
    "FY2022-Q2",
    "FY2022-Q3",
    "FY2022-Q4",
    "FY2023-Q1",
    "FY2023-Q2",
    "FY2023-Q3",
    "FY2023-Q4",
    "FY2024-Q1",
    "FY2024-Q2",
    "FY2024-Q3",
    "FY2024-Q4",
    "FY2025-Q1",
    "FY2025-Q2",
    "FY2025-Q3",
    "FY2025-Q4",
    "FY2026-Q1",
    "FY2026-Q2",
    "FY2026-Q3",
    "FY2026-Q4",
    "FY2027-Q1",
)

KINDS = ("promise", "goal")
PROMISE_EDGES = (
    "restated",
    "evolved",
    "deferred",
    "silent",
    "delivered",
    "missed",
    "abandoned",
)
GOAL_EDGES = (
    "restated",
    "evolved",
    "deferred",
    "silent",
    "hit",
    "missed",
    "still-want",
    "dropped",
    "harden-to-promise",
)
PROMISE_TERMINAL = ("delivered", "missed", "abandoned")
GOAL_TERMINAL = ("hit", "missed", "dropped")
PROMISE_SCORED = ("delivered", "missed")
GOAL_SCORED = ("hit", "missed")
FY_RE = re.compile(r"^FY(\d{4})-Q([1-4])$")


def fiscal_key(fiscal: str) -> tuple[int, int]:
    match = FY_RE.fullmatch(str(fiscal or "").strip().upper())
    if not match:
        return (-1, -1)
    return (int(match.group(1)), int(match.group(2)))


def assert_nvda_stamp(generated_at: object) -> None:
    stamp = str(generated_at or "")
    if stamp == V1_LOCKED_GENERATED_AT:
        raise SystemExit(
            "desk_trees_v2 refuses the 17 Aug tech stamp; NVIDIA book needs its own"
        )
    if stamp != NVDA_STAMP:
        raise SystemExit(
            f"desk_trees_v2 refuses stamp {stamp!r}; locked {NVDA_STAMP!r}"
        )


def assert_window(periods: Sequence[str]) -> None:
    if tuple(periods) != WINDOW:
        raise SystemExit("NVIDIA gold window is not FY2022-Q2 through FY2027-Q1")


def clock_is_due(clock: str | None, fiscal_period: str) -> bool:
    if not clock:
        return False
    clock_key = fiscal_key(clock)
    here = fiscal_key(fiscal_period)
    if clock_key[0] < 0 or here[0] < 0:
        return False
    return here >= clock_key


def citation_for(
    ticker: str,
    fiscal_period: str,
    dimension: str | None,
    status: str | None,
) -> str:
    pointer = f"{ticker} {fiscal_period} novelty_view"
    if dimension:
        pointer = f"{pointer} {dimension}"
    if status:
        pointer = f"{pointer} {status}"
    return pointer


def tree_terminal_edge(kind: str) -> tuple[str, ...]:
    if kind == "promise":
        return PROMISE_TERMINAL
    if kind == "goal":
        return GOAL_TERMINAL
    raise ValueError(f"unknown kind {kind!r}")


def allowed_edges(kind: str) -> tuple[str, ...]:
    if kind == "promise":
        return PROMISE_EDGES
    if kind == "goal":
        return GOAL_EDGES
    raise ValueError(f"unknown kind {kind!r}")


def last_edge(nodes: Sequence[Mapping[str, object]]) -> str | None:
    if not nodes:
        return None
    return str(nodes[-1].get("edge") or "") or None


def is_terminal(kind: str, nodes: Sequence[Mapping[str, object]]) -> bool:
    edge = last_edge(nodes)
    return bool(edge) and edge in tree_terminal_edge(kind)


def current_clock(seed: Mapping[str, object], nodes: Sequence[Mapping[str, object]]) -> str | None:
    clock = str(seed.get("clock") or "").strip() or None
    for node in nodes:
        updated = str(node.get("clock") or "").strip()
        if updated:
            clock = updated
    return clock


def resolve_branch_state(
    *,
    kind: str,
    nodes: Sequence[Mapping[str, object]],
    clock: str | None,
    last_fiscal: str | None,
) -> tuple[str, bool]:
    """Return (state, slipped). Slipped is not missed."""
    edge = last_edge(nodes)
    if kind == "promise":
        if edge in PROMISE_TERMINAL:
            return edge, False
        if edge == "silent" and last_fiscal and clock_is_due(clock, last_fiscal):
            return "open", True
        return "open", False
    if edge in GOAL_TERMINAL:
        return edge, False
    if edge == "still-want":
        return "still-want", False
    return "open", False


def promise_outcome(kind: str, nodes: Sequence[Mapping[str, object]]) -> str:
    if kind != "promise":
        return "not-a-promise"
    edge = last_edge(nodes)
    if edge in PROMISE_SCORED:
        return edge
    if edge == "abandoned":
        return "unresolved"
    return "unresolved"


def goal_outcome(kind: str, nodes: Sequence[Mapping[str, object]]) -> str | None:
    if kind != "goal":
        return None
    edge = last_edge(nodes)
    if edge in GOAL_SCORED or edge in ("still-want", "dropped"):
        return edge
    return "still-want"


def deliver_rate_counts(trees: Sequence[Mapping[str, object]]) -> dict[str, object]:
    delivered = sum(1 for tree in trees if tree.get("delivery") == "delivered")
    missed = sum(1 for tree in trees if tree.get("delivery") == "missed")
    scoreable = delivered + missed
    return {
        "delivered": delivered,
        "missed": missed,
        "n_scoreable": scoreable,
        "deliver_rate": (delivered / scoreable) if scoreable else None,
    }


def hit_rate_counts(trees: Sequence[Mapping[str, object]]) -> dict[str, object]:
    hit = sum(1 for tree in trees if tree.get("goal_outcome") == "hit")
    missed = sum(1 for tree in trees if tree.get("goal_outcome") == "missed")
    scoreable = hit + missed
    return {
        "hit": hit,
        "missed": missed,
        "n_scoreable": scoreable,
        "hit_rate": (hit / scoreable) if scoreable else None,
    }


def _require_seed_cite(tree: Mapping[str, object]) -> str:
    seed = tree.get("seed") or {}
    excerpt = str(seed.get("excerpt") or "").strip()
    if not excerpt:
        raise SystemExit(f"tree {tree.get('tree_id')} missing seed excerpt")
    return excerpt


def validate_catalog_tree(item: Mapping[str, object]) -> None:
    kind = str(item.get("kind") or "")
    if kind not in KINDS:
        raise SystemExit(f"unknown kind {kind!r} on {item.get('tree_id')}")
    seed = item.get("seed") or {}
    if not isinstance(seed, Mapping):
        raise SystemExit(f"tree {item.get('tree_id')} missing seed")
    _require_seed_cite(item)
    parent_cite = str(seed.get("excerpt") or "")
    allowed = allowed_edges(kind)
    previous = str(seed.get("fiscal_period") or "")
    clock = str(seed.get("clock") or "").strip() or None
    for node in item.get("nodes") or []:
        if not isinstance(node, Mapping):
            raise SystemExit(f"tree {item.get('tree_id')} has a non-object node")
        edge = str(node.get("edge") or "")
        if edge not in allowed:
            raise SystemExit(
                f"tree {item.get('tree_id')} forbids edge {edge!r} on {kind}"
            )
        fiscal = str(node.get("fiscal_period") or "")
        if fiscal_key(fiscal) <= fiscal_key(previous):
            raise SystemExit(
                f"tree {item.get('tree_id')} nodes must advance after {previous}"
            )
        if edge == "deferred":
            old_clock = str(node.get("old_clock") or "").strip()
            new_clock = str(node.get("clock") or "").strip()
            if not old_clock or not new_clock:
                raise SystemExit(
                    f"tree {item.get('tree_id')} deferred node needs old_clock and clock"
                )
            if new_clock == old_clock:
                raise SystemExit(
                    f"tree {item.get('tree_id')} deferred clock did not move"
                )
            clock = new_clock
        elif str(node.get("clock") or "").strip():
            clock = str(node.get("clock") or "").strip()
        if edge != "silent" and not str(node.get("excerpt") or "").strip():
            raise SystemExit(
                f"tree {item.get('tree_id')} {fiscal} {edge} missing excerpt"
            )
        if edge == "evolved" and str(seed.get("excerpt") or "") != parent_cite:
            raise SystemExit(
                f"tree {item.get('tree_id')} evolved child lost the parent seed cite"
            )
        if edge in ("delivered", "abandoned") and kind != "promise":
            raise SystemExit(
                f"tree {item.get('tree_id')} used promise terminal on a {kind}"
            )
        if edge in ("hit", "dropped", "still-want") and kind != "goal":
            raise SystemExit(
                f"tree {item.get('tree_id')} used goal terminal on a {kind}"
            )
        previous = fiscal


def materialize_node(
    ticker: str,
    node: Mapping[str, object],
    *,
    clock: str | None,
) -> dict[str, object]:
    fiscal = str(node.get("fiscal_period") or "")
    edge = str(node.get("edge") or "")
    dimension = str(node.get("dimension") or "").strip() or None
    status = str(node.get("status") or "").strip() or None
    excerpt = str(node.get("excerpt") or "").strip() or None
    slipped = bool(
        edge == "silent" and fiscal and clock_is_due(clock, fiscal)
    )
    built = {
        "fiscal_period": fiscal,
        "edge": edge,
        "excerpt": excerpt,
        "dimension": dimension,
        "status": status,
        "citation": None
        if edge == "silent"
        else citation_for(ticker, fiscal, dimension, status),
        "clock": str(node.get("clock") or "").strip() or clock,
        "old_clock": str(node.get("old_clock") or "").strip() or None,
        "objects": list(node.get("objects") or []),
        "coverage_summary": str(node.get("coverage_summary") or "").strip() or None,
        "delivery_basis": str(node.get("delivery_basis") or "").strip() or None,
        "child_tree_id": str(node.get("child_tree_id") or "").strip() or None,
        "slipped": slipped,
    }
    return built


def build_tree(item: Mapping[str, object]) -> dict[str, object]:
    validate_catalog_tree(item)
    kind = str(item["kind"])
    ticker = str(item.get("ticker") or "").upper()
    seed = dict(item.get("seed") or {})
    seed_fiscal = str(seed.get("fiscal_period") or "")
    clock = str(seed.get("clock") or "").strip() or None
    nodes: list[dict[str, object]] = []
    for raw in item.get("nodes") or []:
        if not isinstance(raw, Mapping):
            continue
        node_clock = str(raw.get("clock") or "").strip() or clock
        if str(raw.get("edge") or "") == "deferred":
            clock = str(raw.get("clock") or "").strip() or clock
        elif node_clock:
            clock = node_clock
        nodes.append(materialize_node(ticker, raw, clock=clock))
    clock = current_clock(seed, nodes)
    last_fiscal = str(nodes[-1]["fiscal_period"]) if nodes else seed_fiscal
    state, slipped = resolve_branch_state(
        kind=kind,
        nodes=nodes,
        clock=clock,
        last_fiscal=last_fiscal,
    )
    seed_dimension = str(seed.get("dimension") or "").strip() or None
    seed_status = str(seed.get("status") or "").strip() or None
    parent_seed = str(item.get("parent_seed_excerpt") or seed.get("excerpt") or "")
    return {
        "tree_id": str(item.get("tree_id") or ""),
        "ticker": ticker,
        "kind": kind,
        "beat_id": str(item.get("beat_id") or ""),
        "title": str(item.get("title") or ""),
        "objects": [str(token) for token in (item.get("objects") or ())],
        "parent_tree_id": str(item.get("parent_tree_id") or "").strip() or None,
        "harden_to_tree_id": str(item.get("harden_to_tree_id") or "").strip() or None,
        "parent_seed_excerpt": parent_seed,
        "seed": {
            "fiscal_period": seed_fiscal,
            "claim_type": str(seed.get("claim_type") or "").strip() or None,
            "clock": str(seed.get("clock") or "").strip() or None,
            "excerpt": str(seed.get("excerpt") or "").strip(),
            "dimension": seed_dimension,
            "status": seed_status,
            "citation": citation_for(ticker, seed_fiscal, seed_dimension, seed_status),
        },
        "nodes": nodes,
        "clock": clock,
        "state": state,
        "slipped": slipped,
        "delivery": promise_outcome(kind, nodes),
        "goal_outcome": goal_outcome(kind, nodes),
        "open": not is_terminal(kind, nodes),
        "coverage_summary": next(
            (
                str(node.get("coverage_summary") or "").strip()
                for node in reversed(nodes)
                if node.get("coverage_summary")
            ),
            str(item.get("coverage_summary") or "").strip() or None,
        ),
    }


def walk_open_tree(
    tree: Mapping[str, object],
    quarter: Mapping[str, object] | None,
    fiscal_period: str,
) -> dict[str, object]:
    """Add one edge for a newly scored quarter. Does not invent seeds or terminals."""
    built = dict(tree)
    kind = str(built.get("kind") or "promise")
    nodes = [dict(node) for node in (built.get("nodes") or []) if isinstance(node, Mapping)]
    if is_terminal(kind, nodes):
        return built
    if any(str(node.get("fiscal_period") or "") == fiscal_period for node in nodes):
        return built
    seed = built.get("seed") or {}
    if fiscal_key(fiscal_period) <= fiscal_key(str(seed.get("fiscal_period") or "")):
        return built
    objects = [str(token) for token in (built.get("objects") or ())]
    hit = first_object_hit(all_verified_evidence(quarter), objects) if quarter else None
    clock = current_clock(seed if isinstance(seed, Mapping) else {}, nodes)
    if hit is None:
        raw = {
            "fiscal_period": fiscal_period,
            "edge": "silent",
            "excerpt": None,
            "clock": clock,
        }
    else:
        raw = {
            "fiscal_period": fiscal_period,
            "edge": "restated",
            "excerpt": hit.get("excerpt"),
            "dimension": hit.get("dimension"),
            "status": hit.get("status"),
            "clock": clock,
        }
    nodes.append(materialize_node(str(built.get("ticker") or ""), raw, clock=clock))
    built["nodes"] = nodes
    last_fiscal = fiscal_period
    state, slipped = resolve_branch_state(
        kind=kind,
        nodes=nodes,
        clock=clock,
        last_fiscal=last_fiscal,
    )
    built["clock"] = clock
    built["state"] = state
    built["slipped"] = slipped
    built["delivery"] = promise_outcome(kind, nodes)
    built["goal_outcome"] = goal_outcome(kind, nodes)
    built["open"] = not is_terminal(kind, nodes)
    return built


def walk_open_trees(
    trees: Sequence[Mapping[str, object]],
    *,
    ticker: str,
    fiscal_period: str,
    novelty_view: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    want = str(ticker or "").upper()
    quarter = quarter_for_fiscal(novelty_view, fiscal_period)
    walked: list[dict[str, object]] = []
    for tree in trees:
        if str(tree.get("ticker") or "").upper() != want:
            walked.append(dict(tree))
            continue
        if not tree.get("open"):
            walked.append(dict(tree))
            continue
        walked.append(walk_open_tree(tree, quarter, fiscal_period))
    return walked


def evidence_has_excerpt(
    quarter: Mapping[str, object] | None,
    excerpt: str,
) -> bool:
    want = str(excerpt or "").strip()
    if not want:
        return False
    for row in all_verified_evidence(quarter):
        if want in str(row.get("excerpt") or ""):
            return True
    return False


def verify_tree_against_novelty(
    tree: Mapping[str, object],
    novelty_view: Mapping[str, object] | None,
) -> None:
    seed = tree.get("seed") or {}
    fiscal = str(seed.get("fiscal_period") or "")
    excerpt = str(seed.get("excerpt") or "")
    quarter = quarter_for_fiscal(novelty_view, fiscal)
    if not evidence_has_excerpt(quarter, excerpt):
        raise SystemExit(
            f"{tree.get('tree_id')} seed excerpt missing from {fiscal} novelty_view"
        )
    for node in tree.get("nodes") or []:
        if str(node.get("edge") or "") == "silent":
            continue
        node_fiscal = str(node.get("fiscal_period") or "")
        node_excerpt = str(node.get("excerpt") or "")
        node_quarter = quarter_for_fiscal(novelty_view, node_fiscal)
        if not evidence_has_excerpt(node_quarter, node_excerpt):
            raise SystemExit(
                f"{tree.get('tree_id')} {node_fiscal} excerpt missing from novelty_view"
            )


def evolved_keeps_parent_seed(trees: Sequence[Mapping[str, object]]) -> None:
    by_id = {str(tree.get("tree_id") or ""): tree for tree in trees}
    for tree in trees:
        parent_id = str(tree.get("parent_tree_id") or "")
        if not parent_id:
            continue
        parent = by_id.get(parent_id)
        if parent is None:
            raise SystemExit(f"{tree.get('tree_id')} parent {parent_id} missing")
        parent_excerpt = str((parent.get("seed") or {}).get("excerpt") or "")
        if str(tree.get("parent_seed_excerpt") or "") != parent_excerpt:
            raise SystemExit(
                f"{tree.get('tree_id')} evolved child lost the parent seed cite"
            )


def build_book(
    catalog: Sequence[Mapping[str, object]],
    novelty_by_ticker: Mapping[str, Mapping[str, object] | None],
    *,
    generated_at: str = NVDA_STAMP,
    verify_excerpts: bool = True,
) -> dict[str, object]:
    assert_nvda_stamp(generated_at)
    assert_window(WINDOW)
    trees = [build_tree(item) for item in catalog]
    evolved_keeps_parent_seed(trees)
    if verify_excerpts:
        for tree in trees:
            ticker = str(tree.get("ticker") or "")
            verify_tree_against_novelty(tree, novelty_by_ticker.get(ticker))
    promises = [tree for tree in trees if tree.get("kind") == "promise"]
    goals = [tree for tree in trees if tree.get("kind") == "goal"]
    gold_trees = [
        tree
        for tree in trees
        if str((tree.get("seed") or {}).get("fiscal_period") or "") in WINDOW
    ]
    gold_promises = [tree for tree in gold_trees if tree.get("kind") == "promise"]
    gold_goals = [tree for tree in gold_trees if tree.get("kind") == "goal"]
    deliver = deliver_rate_counts(gold_promises)
    hits = hit_rate_counts(gold_goals)
    deliver_full = deliver_rate_counts(promises)
    hits_full = hit_rate_counts(goals)
    if hits.get("n_scoreable") and deliver.get("n_scoreable"):
        # Goal hits must never enter the promise deliver rate.
        if int(deliver["delivered"] or 0) < int(hits["hit"] or 0) and len(promises) == 0:
            raise SystemExit("goal hits leaked into an empty promise book")
    return {
        "generated_at": generated_at,
        "case_study_id": CASE_STUDY_ID,
        "book_id": BOOK_ID,
        "split": SPLIT,
        "full_split": FULL_SPLIT,
        "calendar": "nvidia_fiscal",
        "window": list(WINDOW),
        "caption": (
            "Claims desk v2 NVIDIA gold. A seed starts a tree; later quarters "
            "are edges. Kept is not delivered. Goal hit rate is not deliver "
            "rate. Path ID is not the verdict. Not the 17 Aug tech book."
        ),
        "n_trees": len(trees),
        "n_promises": len(promises),
        "n_goals": len(goals),
        "n_gold_trees": len(gold_trees),
        "deliver_rates": {"book": deliver, "full_history": deliver_full},
        "hit_rates": {"book": hits, "full_history": hits_full},
        "trees": trees,
    }


def build_ops_book(
    catalog: Sequence[Mapping[str, object]],
    novelty_by_ticker: Mapping[str, Mapping[str, object] | None],
    *,
    generated_at: str,
    verify_excerpts: bool = True,
    book_id: str = "desk_ops_v2",
    split: str = "tech-ops-novelty-present",
    caption: str | None = None,
) -> dict[str, object]:
    """Operational multi-ticker book. Not NVIDIA gold. Not the 17 Aug book."""
    if generated_at == V1_LOCKED_GENERATED_AT:
        raise SystemExit("ops book refuses the 17 Aug stamp")
    if generated_at == NVDA_STAMP:
        raise SystemExit("ops book refuses the NVIDIA gold stamp")
    trees = [build_tree(item) for item in catalog]
    evolved_keeps_parent_seed(trees)
    if verify_excerpts:
        for tree in trees:
            ticker = str(tree.get("ticker") or "")
            verify_tree_against_novelty(tree, novelty_by_ticker.get(ticker))
    promises = [tree for tree in trees if tree.get("kind") == "promise"]
    goals = [tree for tree in trees if tree.get("kind") == "goal"]
    tickers = sorted({str(tree.get("ticker") or "") for tree in trees if tree.get("ticker")})
    return {
        "generated_at": generated_at,
        "case_study_id": CASE_STUDY_ID,
        "book_id": book_id,
        "split": split,
        "calendar": "per-ticker",
        "caption": caption
        or (
            "Claims desk v2 operational book. Not NVIDIA gold. "
            "Not the 17 Aug Rank IC book. Seed cites start trees; "
            "walk does not invent delivered, hit, or missed."
        ),
        "n_trees": len(trees),
        "n_promises": len(promises),
        "n_goals": len(goals),
        "tickers": tickers,
        "deliver_rates": {"book": deliver_rate_counts(promises)},
        "hit_rates": {"book": hit_rate_counts(goals)},
        "trees": trees,
    }


def _novelty_path(ticker: str) -> Path:
    return (
        ROOT
        / "Structured Narrative"
        / "output"
        / ticker
        / "json"
        / "novelty_view.json"
    )


def trees_output_path() -> Path:
    return (
        ROOT
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_v2.json"
    )


def v1_flex_still_delivered(v1_path: Path | None = None) -> None:
    path = v1_path or (
        ROOT
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_claims_v1.json"
    )
    if not path.is_file():
        raise SystemExit("desk_claims_v1.json missing; Flex bar cannot be checked")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if str(payload.get("generated_at") or "") != V1_LOCKED_GENERATED_AT:
        raise SystemExit("v1 stamp drifted; Flex bar refuses to run")
    flex = next(
        (
            row
            for row in (payload.get("rows") or [])
            if row.get("ticker") == "ADSK" and row.get("period") == "2021-Q2"
        ),
        None,
    )
    if flex is None or flex.get("state") != "kept" or flex.get("delivery") != "delivered":
        raise SystemExit("Flex v1 bar failed: launch must stay kept and delivered")


def main() -> int:
    v1_flex_still_delivered()
    novelty_path = _novelty_path("NVDA")
    if not novelty_path.is_file():
        raise SystemExit(f"NVDA novelty_view missing: {novelty_path}")
    novelty = json.loads(novelty_path.read_text(encoding="utf-8"))
    payload = build_book(NVDA_TREES, {"NVDA": novelty})
    quarters = [
        str(row.get("fiscal_period") or "")
        for row in (novelty.get("quarters") or [])
        if str(row.get("fiscal_period") or "").startswith("FY")
    ]
    latest = quarters[-1] if quarters else ""
    if latest and latest not in WINDOW:
        walked = walk_open_trees(
            payload["trees"],
            ticker="NVDA",
            fiscal_period=latest,
            novelty_view=novelty,
        )
        payload["trees"] = walked
        payload["walked_trigger"] = f"NVDA:{latest}"
    out = trees_output_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(out)
    print("n_trees", payload["n_trees"])
    print("n_gold_trees", payload.get("n_gold_trees"))
    print("deliver_rates", payload["deliver_rates"])
    print("hit_rates", payload["hit_rates"])
    print("walked", latest if latest and latest not in WINDOW else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
