"""Quote flatten for Claims Trees. No Streamlit."""
from __future__ import annotations

from services.earnings_monitor.dashboard.claims_quotes import (
    filter_quote_rows,
    quote_rows,
    tree_outcome,
)


def _tree() -> dict:
    return {
        "tree_id": "nvda-example",
        "ticker": "NVDA",
        "title": "Ship the part",
        "kind": "promise",
        "clock": "FY2025-Q4",
        "slipped": False,
        "state": "delivered",
        "delivery": "delivered",
        "goal_outcome": None,
        "seed": {
            "fiscal_period": "FY2025-Q1",
            "excerpt": "We will ship the part in Q4.",
            "citation": "c-seed",
            "clock": "FY2025-Q4",
        },
        "nodes": [
            {
                "fiscal_period": "FY2025-Q2",
                "edge": "restated",
                "excerpt": "We still plan to ship the part in Q4.",
                "citation": "c-change",
            },
            {
                "fiscal_period": "FY2025-Q3",
                "edge": "silent",
                "excerpt": None,
            },
            {
                "fiscal_period": "FY2025-Q4",
                "edge": "delivered",
                "excerpt": "We shipped the part this quarter.",
                "citation": "c-close",
            },
        ],
    }


def test_quote_rows_seed_change_close_skip_silent() -> None:
    rows = quote_rows([_tree()])
    assert [row["role"] for row in rows] == ["seed", "change", "close"]
    assert [row["edge"] for row in rows] == ["seed", "restated", "delivered"]
    assert rows[0]["excerpt"].startswith("We will ship")
    assert rows[1]["excerpt"].startswith("We still plan")
    assert rows[2]["excerpt"].startswith("We shipped")
    assert all(row["outcome"] == "delivered" for row in rows)


def test_slipped_tag_on_every_row() -> None:
    tree = {
        "tree_id": "open-slip",
        "ticker": "MSFT",
        "title": "Briefing",
        "kind": "promise",
        "clock": "FY2017-Q4",
        "slipped": True,
        "state": "open",
        "delivery": "unresolved",
        "seed": {
            "fiscal_period": "FY2017-Q2",
            "excerpt": "We will hold a briefing in May.",
        },
        "nodes": [
            {
                "fiscal_period": "FY2026-Q4",
                "edge": "silent",
                "excerpt": None,
            }
        ],
    }
    rows = quote_rows([tree])
    assert len(rows) == 1
    assert rows[0]["role"] == "seed"
    assert rows[0]["slipped"] is True
    assert tree_outcome(tree) == "slipped"
    assert rows[0]["outcome"] == "slipped"


def test_filter_quote_rows_by_outcome_and_role() -> None:
    rows = quote_rows([_tree()])
    closed = filter_quote_rows(rows, outcomes=["delivered"], roles=["close"])
    assert len(closed) == 1
    assert closed[0]["role"] == "close"
    empty = filter_quote_rows(rows, outcomes=["missed"])
    assert empty == []
