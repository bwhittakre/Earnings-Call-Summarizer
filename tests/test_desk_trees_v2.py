"""Fixture tests for claims desk v2 trees. Does not load live novelty_view."""
from __future__ import annotations

import pytest

from scripts._desk_claims_v1 import LOCKED_GENERATED_AT
from scripts._desk_trees_v2 import (
    BECAME_PROMISE,
    KIND_LABEL_PROMISE_WAS_GOAL,
    NVDA_STAMP,
    WINDOW,
    build_book,
    build_tree,
    conversion_counts,
    current_clock,
    deliver_rate_counts,
    hit_rate_counts,
    known_delivered_caption,
    known_delivered_counts,
    tree_aged_bucket,
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


def _goal_became_delivered() -> dict:
    """One tree: want → became a promise → delivered. Not a second seed."""
    return {
        "tree_id": "adsk-want-flex-mix",
        "ticker": "ADSK",
        "kind": "goal",
        "beat_id": "flex",
        "title": "We want Flex mix",
        "objects": ("Flex",),
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
                "clock": "FY2022-Q3",
                "excerpt": "At the end of September, we will launch Flex.",
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            {
                "fiscal_period": "FY2022-Q3",
                "edge": "delivered",
                "excerpt": "We're seeing a large percent of Flex business coming in.",
                "dimension": "competitive_position",
                "status": "verbatim",
                "coverage_summary": "Flex showed up as live mix.",
                "delivery_basis": "Cite treats Flex as live business.",
            },
        ),
    }


def _goal_became_open() -> dict:
    item = _goal_became_delivered()
    item["nodes"] = (item["nodes"][0],)
    return item


def _goal_hit_unconverted() -> dict:
    return {
        "tree_id": "adsk-want-flex-mix-hit",
        "ticker": "ADSK",
        "kind": "goal",
        "beat_id": "flex-hit",
        "title": "We want Flex mix",
        "objects": ("Flex",),
        "seed": {
            "fiscal_period": "FY2022-Q1",
            "excerpt": "We want Flex to become a meaningful mix.",
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
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
        [_flex_seed(), _goal_hit_unconverted()],
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


def test_became_promise_stays_one_tree_until_delivered() -> None:
    opened = build_tree(_goal_became_open())
    assert opened["kind"] == "goal"
    assert opened["current_kind"] == "promise"
    assert opened["kind_label"] == KIND_LABEL_PROMISE_WAS_GOAL
    assert opened["goal_outcome"] == BECAME_PROMISE
    assert opened["delivery"] == "unresolved"
    assert opened["state"] == "open"
    assert opened["open"] is True
    assert opened["nodes"][0]["edge"] == "harden-to-promise"
    assert opened["nodes"][0]["edge_label"] == "became a promise"
    assert opened["clock"] == "FY2022-Q3"

    closed = build_tree(_goal_became_delivered())
    assert closed["goal_outcome"] == BECAME_PROMISE
    assert closed["delivery"] == "delivered"
    assert closed["state"] == "delivered"
    assert closed["open"] is False
    assert closed["kind"] == "goal"
    assert closed["current_kind"] == "promise"


def test_post_conversion_hit_rejected() -> None:
    bad = _goal_became_open()
    nodes = list(bad["nodes"])
    nodes.append(
        {
            "fiscal_period": "FY2022-Q3",
            "edge": "hit",
            "excerpt": "We're seeing a large percent of Flex business coming in.",
            "dimension": "competitive_position",
            "status": "verbatim",
        }
    )
    bad["nodes"] = tuple(nodes)
    with pytest.raises(SystemExit, match="after became a promise"):
        build_tree(bad)


def test_same_call_harden_may_share_seed_fiscal() -> None:
    tree = build_tree(
        {
            "tree_id": "same-call-want-will",
            "ticker": "ADSK",
            "kind": "goal",
            "beat_id": "flex",
            "title": "Want then will same call",
            "objects": ("Flex",),
            "seed": {
                "fiscal_period": "FY2022-Q2",
                "excerpt": "We want Flex to become a meaningful mix.",
                "dimension": "competitive_position",
                "status": "verbatim",
            },
            "nodes": (
                {
                    "fiscal_period": "FY2022-Q2",
                    "edge": "harden-to-promise",
                    "clock": "FY2022-Q3",
                    "excerpt": "At the end of September, we will launch Flex.",
                    "dimension": "competitive_position",
                    "status": "verbatim",
                },
            ),
        }
    )
    assert tree["goal_outcome"] == BECAME_PROMISE
    assert tree["open"] is True


def test_became_promise_counts_as_deliver_not_hit() -> None:
    book = build_book(
        [_goal_became_delivered()],
        {},
        generated_at=NVDA_STAMP,
        verify_excerpts=False,
    )
    full_deliver = book["deliver_rates"]["full_history"]
    full_hits = book["hit_rates"]["full_history"]
    gold_deliver = book["deliver_rates"]["book"]
    assert book["n_goals"] == 1
    assert book["n_promises"] == 0
    assert book["conversion"]["n_became_promise"] == 1
    assert book["conversion"]["harden_rate"] == 1.0
    assert full_deliver["delivered"] == 1
    assert full_deliver["n_scoreable"] == 1
    assert full_hits["hit"] == 0
    assert full_hits["n_scoreable"] == 0
    assert gold_deliver["n_scoreable"] == 0


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


def test_unknown_bucket_rejected() -> None:
    item = _flex_seed()
    item["bucket"] = "supply"
    with pytest.raises(SystemExit, match="unknown bucket"):
        build_tree(item)


def test_missing_bucket_allowed() -> None:
    tree = build_tree(_flex_seed())
    assert tree["bucket"] is None


def test_build_tree_keeps_bucket_and_walk_does_not_invent() -> None:
    item = _flex_seed()
    item["nodes"] = ()
    item["bucket"] = "demand"
    tree = build_tree(item)
    assert tree["bucket"] == "demand"
    assert tree["seed"]["dimension"] == "competitive_position"
    walked = walk_open_tree(
        tree,
        {
            "fiscal_period": "FY2022-Q3",
            "novelties": [
                {
                    "dimension": "management_confidence",
                    "evidence": [
                        {
                            "excerpt": "Flex demand remains strong this quarter.",
                            "verified": True,
                            "status": "verbatim",
                        }
                    ],
                }
            ],
        },
        "FY2022-Q3",
    )
    assert walked["bucket"] == "demand"
    assert walked["nodes"][-1]["dimension"] == "management_confidence"

    bare = build_tree(_flex_seed())
    assert bare["bucket"] is None
    silent = walk_open_tree(bare, None, "FY2022-Q4")
    assert silent["bucket"] is None


def test_bucket_does_not_change_rates() -> None:
    plain = _goal_became_delivered()
    tagged = dict(plain)
    tagged["bucket"] = "demand"
    book_plain = build_book([plain], {}, generated_at=NVDA_STAMP, verify_excerpts=False)
    book_tagged = build_book([tagged], {}, generated_at=NVDA_STAMP, verify_excerpts=False)
    assert book_plain["deliver_rates"] == book_tagged["deliver_rates"]
    assert book_plain["hit_rates"] == book_tagged["hit_rates"]
    assert book_plain["conversion"] == book_tagged["conversion"]
    assert conversion_counts(book_tagged["trees"]) == book_plain["conversion"]


def test_expired_closes_and_does_not_score() -> None:
    item = {
        "tree_id": "ibm-promontory-watson",
        "ticker": "IBM",
        "kind": "promise",
        "beat_id": "promontory-watson",
        "title": "Train Watson",
        "objects": ("Watson",),
        "expire": "FY2018-Q3",
        "seed": {
            "fiscal_period": "FY2016-Q3",
            "excerpt": "We will train Watson on Promontory.",
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": (
            {
                "fiscal_period": "FY2018-Q3",
                "edge": "expired",
                "excerpt": "Never followed up; completeness unfeasible.",
            },
        ),
    }
    tree = build_tree(item)
    assert tree["open"] is False
    assert tree["state"] == "expired"
    assert tree["delivery"] == "expired"
    assert tree["expire"] == "FY2018-Q3"
    assert deliver_rate_counts([tree])["n_scoreable"] == 0
    assert deliver_rate_counts([tree])["deliver_rate"] is None
    assert tree_aged_bucket(tree, "FY2018-Q3") == "unknown"
    counts = known_delivered_counts([tree], "FY2018-Q3")
    assert counts["n_unknown"] == 1
    assert counts["n_confirmed"] == 0
    assert counts["known_delivered_rate"] == 0.0
    assert counts["settled_share"] == 0.0
    caption = known_delivered_caption(counts)
    assert "This is what we know has been delivered" in caption
    assert "unknown" in caption


def test_known_delivered_moves_off_unknown_with_evidence() -> None:
    expired = {
        "tree_id": "a",
        "ticker": "IBM",
        "kind": "promise",
        "title": "x",
        "objects": ("X",),
        "seed": {
            "fiscal_period": "FY2016-Q3",
            "excerpt": "We will do X.",
            "status": "verbatim",
        },
        "nodes": ({"fiscal_period": "FY2018-Q3", "edge": "expired"},),
    }
    dropped = dict(expired)
    dropped["tree_id"] = "b"
    dropped["nodes"] = (
        {
            "fiscal_period": "FY2018-Q3",
            "edge": "abandoned",
            "excerpt": "We walked away from X.",
        },
    )
    delivered = _flex_seed()
    counts = known_delivered_counts(
        [build_tree(expired), build_tree(dropped), build_tree(delivered)],
        "FY2022-Q3",
    )
    assert counts["n_confirmed"] == 1
    assert counts["n_withdrawn"] == 1
    assert counts["n_unknown"] == 1
    assert counts["n_aged"] == 3
    assert counts["known_delivered_rate"] == 1 / 3
    assert counts["settled_share"] == 2 / 3


def test_deferred_moves_current_clock() -> None:
    tree = build_tree(_deferred_seed())
    seed = tree["seed"]
    assert seed["clock"] == "FY2023-Q1"
    assert current_clock(seed, tree["nodes"]) == "FY2024-Q1"
    assert tree["clock"] == "FY2024-Q1"
    assert tree["open"] is True
    assert tree["delivery"] == "unresolved"


def test_walk_does_not_invent_expire_or_quant() -> None:
    item = _flex_seed()
    item["nodes"] = ()
    item["expire"] = "FY2024-Q1"
    item["quant"] = {"measure": 22, "op": "gte", "threshold": 150, "unit": "million"}
    tree = build_tree(item)
    walked = walk_open_tree(tree, None, "FY2022-Q3")
    assert walked["expire"] == "FY2024-Q1"
    assert walked["quant"]["measure"] == 22
    assert walked["nodes"][-1]["edge"] == "silent"
    assert walked["open"] is True
