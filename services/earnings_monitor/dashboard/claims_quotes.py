"""Flatten cited quotes from desk trees. No Streamlit. No LLM."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

CHANGE_EDGES = ("restated", "evolved", "deferred", "harden-to-promise")
CLOSE_EDGES = ("delivered", "missed", "abandoned", "hit", "dropped")


def tree_outcome(tree: Mapping[str, Any]) -> str:
    kind = str(tree.get("kind") or "")
    delivery = str(tree.get("delivery") or "")
    goal = str(tree.get("goal_outcome") or "")
    state = str(tree.get("state") or "")
    if kind == "promise" and delivery == "delivered":
        return "delivered"
    if kind == "goal" and goal == "hit":
        return "hit"
    if delivery == "missed" or goal == "missed":
        return "missed"
    if delivery == "abandoned" or state == "abandoned":
        return "abandoned"
    if goal == "dropped" or state == "dropped":
        return "dropped"
    if tree.get("slipped"):
        return "slipped"
    if goal == "still-want" or state == "still-want":
        return "still-want"
    return "open"


def quote_rows(trees: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per cited quote. Silent nodes are omitted."""
    rows: list[dict[str, Any]] = []
    for tree in trees:
        if not isinstance(tree, Mapping):
            continue
        ticker = str(tree.get("ticker") or "").upper()
        outcome = tree_outcome(tree)
        slipped = bool(tree.get("slipped"))
        kind = str(tree.get("kind") or "")
        clock = str(tree.get("clock") or "").strip() or None
        seed = tree.get("seed") or {}
        excerpt = str(seed.get("excerpt") or "").strip()
        if excerpt:
            rows.append(
                {
                    "ticker": ticker,
                    "tree_id": tree.get("tree_id"),
                    "title": tree.get("title"),
                    "kind": kind,
                    "role": "seed",
                    "fiscal_period": seed.get("fiscal_period"),
                    "edge": "seed",
                    "clock": seed.get("clock") or clock,
                    "slipped": slipped,
                    "state": tree.get("state"),
                    "delivery": tree.get("delivery"),
                    "goal_outcome": tree.get("goal_outcome"),
                    "outcome": outcome,
                    "excerpt": excerpt,
                    "citation": seed.get("citation"),
                }
            )
        for node in tree.get("nodes") or []:
            if not isinstance(node, Mapping):
                continue
            edge = str(node.get("edge") or "")
            text = str(node.get("excerpt") or "").strip()
            if not text:
                continue
            if edge in CHANGE_EDGES:
                role = "change"
            elif edge in CLOSE_EDGES:
                role = "close"
            else:
                continue
            rows.append(
                {
                    "ticker": ticker,
                    "tree_id": tree.get("tree_id"),
                    "title": tree.get("title"),
                    "kind": kind,
                    "role": role,
                    "fiscal_period": node.get("fiscal_period"),
                    "edge": edge,
                    "clock": node.get("clock") or clock,
                    "slipped": slipped,
                    "state": tree.get("state"),
                    "delivery": tree.get("delivery"),
                    "goal_outcome": tree.get("goal_outcome"),
                    "outcome": outcome,
                    "excerpt": text,
                    "citation": node.get("citation"),
                }
            )
    return rows


def filter_quote_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    outcomes: Sequence[str] | None = None,
    kinds: Sequence[str] | None = None,
    roles: Sequence[str] | None = None,
    tickers: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    want_outcomes = {str(item) for item in outcomes} if outcomes else None
    want_kinds = {str(item) for item in kinds} if kinds else None
    want_roles = {str(item) for item in roles} if roles else None
    want_tickers = {str(item).upper() for item in tickers} if tickers else None
    found: list[dict[str, Any]] = []
    for row in rows:
        if want_outcomes is not None and str(row.get("outcome") or "") not in want_outcomes:
            continue
        if want_kinds is not None and str(row.get("kind") or "") not in want_kinds:
            continue
        if want_roles is not None and str(row.get("role") or "") not in want_roles:
            continue
        if want_tickers is not None and str(row.get("ticker") or "").upper() not in want_tickers:
            continue
        found.append(dict(row))
    return found
