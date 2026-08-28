"""Fixture tests for claims desk v2 trees. Does not load live novelty_view."""
from __future__ import annotations

import pytest

from scripts._desk_claims_v1 import LOCKED_GENERATED_AT
from scripts._desk_trees_v2 import (
    NVDA_STAMP,
    WINDOW,
    build_book,
    build_tree,
    deliver_rate_counts,
    hit_rate_counts,
    walk_open_tree,
    walk_open_trees,
)


def _flex_seed() -> dict:
    return {
        "tree_id": "adsk-flex-launch",
        "ticker": "ADSK",
        "kind": "promise",
        "beat_id": "flex",
        "title": "Flex launch",
        "objects": ("Flex",),
        "seed": {
            "fiscal_period": "FY2022-Q2",
            "claim_type": "forward_clock",
            "clock": "FY2022-Q3",
            "excerpt": "At the end of September, we will launch Flex.",
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2022-Q3",
                "edge": "delivered",
                "excerpt": (
                    "One of the things we're seeing with Flex is exactly "
                    "what we expected to see."
                ),
                "dimension": "competitive_position",
                "status": "composite",
                "coverage_summary": "Next quarter treated Flex as live usage.",
                "delivery_basis": "Cite treats Flex as live business.",
            },
        ),
    }


def _deferred_seed() -> dict:
    return {
        "tree_id": "adsk-flex-transaction",
        "ticker": "ADSK",
        "kind": "promise",
        "beat_id": "flex",
        "title": "Flex transaction model",
        "objects": ("Flex",),
        "parent_tree_id": "adsk-flex-launch",
        "parent_seed_excerpt": "At the end of September, we will launch Flex.",
        "seed": {
            "fiscal_period": "FY2022-Q3",
            "claim_type": "forward_clock",
            "clock": "FY2023-Q1",
            "excerpt": "We will move Flex to a transaction model next year.",
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2022-Q4",
                "edge": "deferred",
                "old_clock": "FY2023-Q1",
                "clock": "FY2024-Q1",
                "excerpt": "The Flex transaction model now lands in FY2024.",
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2023-Q1",
                "edge": "silent",
                "clock": "FY2024-Q1",
            },
        ),
    }


def _goal_hit() -> dict:
    return {
        "tree_id": "adsk-want-flex-mix",
        "ticker": "ADSK",
        "kind": "goal",
        "beat_id": "flex",
        "title": "We want Flex mix",
        "objects": ("Flex",),
        "harden_to_tree_id": "adsk-flex-launch",
        "seed": {
            "fiscal_period": "FY2022-Q1",
            "excerpt": "We want Flex to become a meaningful mix.",
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2022-Q2",
                "edge": "harden-to-promise",
                "child_tree_id": "adsk-flex-launch",
                "excerpt": "At the end of September, we will launch Flex.",
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2022-Q3",
                "edge": "hit",
                "excerpt": "We're seeing a large percent of Flex business coming in.",
                "dimension": "competitive_position",
                "status": "verbatim",
                "coverage_summary": "Flex showed up as live mix.",
            },
        ),
    }


def test_window_is_twenty_consecutive_nvda_quarters() -> None:
    assert len(WINDOW) == 20
    assert WINDOW[0] == "FY2022-Q2"
    assert WINDOW[-1] == "FY2027-Q1"


def test_flex_tree_delivered() -> None:
    tree = build_tree(_flex_seed())
    assert tree["state"] == "delivered"
    assert tree["delivery"] == "delivered"
    assert tree["open"] is False
    assert tree["seed"]["excerpt"].startswith("At the end of September")


def test_deferred_clock_stays_open_not_missed() -> None:
    tree = build_tree(_deferred_seed())
    assert tree["nodes"][0]["old_clock"] == "FY2023-Q1"
    assert tree["clock"] == "FY2024-Q1"
    assert tree["delivery"] == "unresolved"
    assert tree["state"] == "open"
    assert tree["slipped"] is False
    assert tree["open"] is True


def test_deferred_same_clock_rejected() -> None:
    bad = _deferred_seed()
    nodes = list(bad["nodes"])
    nodes[0] = dict(nodes[0], clock="FY2023-Q1")
    bad["nodes"] = tuple(nodes)
    with pytest.raises(SystemExit, match="deferred clock did not move"):
        build_tree(bad)


def test_evolved_child_keeps_parent_seed() -> None:
    child = build_tree(_deferred_seed())
    assert child["parent_seed_excerpt"] == "At the end of September, we will launch Flex."
    parent = build_tree(_flex_seed())
    book = build_book(
        [_flex_seed(), _deferred_seed()],
        {},
        generated_at=NVDA_STAMP,
        verify_excerpts=False,
    )
    assert book["trees"][1]["parent_seed_excerpt"] == parent["seed"]["excerpt"]


def test_goal_hit_rate_not_in_deliver_rate() -> None:
    book = build_book(
        [_flex_seed(), _goal_hit()],
        {},
        generated_at=NVDA_STAMP,
        verify_excerpts=False,
    )
    deliver = book["deliver_rates"]["book"]
    hits = book["hit_rates"]["book"]
    full_hits = book["hit_rates"]["full_history"]
    assert deliver["delivered"] == 1
    assert deliver["n_scoreable"] == 1
    assert hits["hit"] == 0
    assert hits["n_scoreable"] == 0
    assert full_hits["hit"] == 1
    assert full_hits["n_scoreable"] == 1
    assert deliver["deliver_rate"] == 1.0
    assert full_hits["hit_rate"] == 1.0
    assert book["n_promises"] == 1
    assert book["n_goals"] == 1
    assert book["n_gold_trees"] == 1


def test_harden_to_promise_is_an_edge() -> None:
    tree = build_tree(_goal_hit())
    assert tree["harden_to_tree_id"] == "adsk-flex-launch"
    assert tree["nodes"][0]["edge"] == "harden-to-promise"
    assert tree["nodes"][0]["child_tree_id"] == "adsk-flex-launch"
    assert tree["goal_outcome"] == "hit"


def test_silent_due_is_slipped_not_missed() -> None:
    item = {
        "tree_id": "open-clock",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "x",
        "title": "open",
        "objects": ("X",),
        "seed": {
            "fiscal_period": "FY2025-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2025-Q2",
            "excerpt": "We will ship X next quarter.",
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {"fiscal_period": "FY2025-Q2", "edge": "silent", "clock": "FY2025-Q2"},
        ),
    }
    tree = build_tree(item)
    assert tree["slipped"] is True
    assert tree["state"] == "open"
    assert tree["delivery"] == "unresolved"
    assert tree["open"] is True


def test_refuses_seventeen_aug_stamp() -> None:
    with pytest.raises(SystemExit, match="17 Aug"):
        build_book([_flex_seed()], {}, generated_at=LOCKED_GENERATED_AT, verify_excerpts=False)


def test_walk_open_tree_restates_without_auto_deliver() -> None:
    tree = build_tree(
        {
            "tree_id": "walk-me",
            "ticker": "NVDA",
            "kind": "promise",
            "beat_id": "x",
            "title": "X",
            "objects": ("Hopper",),
            "seed": {
                "fiscal_period": "FY2025-Q1",
                "claim_type": "forward_clock",
                "clock": "FY2026-Q1",
                "excerpt": "We will ship more Hopper.",
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            "nodes": (),
        }
    )
    quarter = {
        "fiscal_period": "FY2025-Q2",
        "novelties": [
            {
                "dimension": "competitive_position",
                "evidence": [
                    {
                        "excerpt": "Hopper demand remains strong this quarter.",
                        "verified": True,
                        "status": "verbatim",
                    }
                ],
            }
        ],
    }
    walked = walk_open_tree(tree, quarter, "FY2025-Q2")
    assert walked["nodes"][-1]["edge"] == "restated"
    assert walked["delivery"] == "unresolved"
    assert walked["open"] is True


def test_walk_open_trees_skips_other_tickers_and_closed() -> None:
    flex = build_tree(_flex_seed())
    open_tree = build_tree(
        {
            "tree_id": "nvda-open",
            "ticker": "NVDA",
            "kind": "promise",
            "beat_id": "x",
            "title": "X",
            "objects": ("Hopper",),
            "seed": {
                "fiscal_period": "FY2025-Q1",
                "claim_type": "forward_clock",
                "clock": "FY2026-Q1",
                "excerpt": "We will ship more Hopper.",
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            "nodes": (),
        }
    )
    novelty = {
        "quarters": [
            {
                "fiscal_period": "FY2025-Q2",
                "novelties": [
                    {
                        "dimension": "competitive_position",
                        "evidence": [
                            {
                                "excerpt": "No object here.",
                                "verified": True,
                                "status": "verbatim",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    walked = walk_open_trees(
        [flex, open_tree],
        ticker="NVDA",
        fiscal_period="FY2025-Q2",
        novelty_view=novelty,
    )
    assert walked[0]["nodes"] == flex["nodes"]
    assert walked[1]["nodes"][-1]["edge"] == "silent"
    assert walked[1]["slipped"] is False


def test_unresolved_rates_are_none() -> None:
    empty = deliver_rate_counts([])
    assert empty["deliver_rate"] is None
    empty_goals = hit_rate_counts([])
    assert empty_goals["hit_rate"] is None
