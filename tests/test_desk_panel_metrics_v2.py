"""PIT desk_trust / desk_ambition bars. Does not load live novelty_view."""
from __future__ import annotations

import pytest

from scripts._desk_claims_v1 import LOCKED_GENERATED_AT
from scripts._desk_trees_v2 import NVDA_STAMP, WINDOW, v1_flex_still_delivered
from scripts._desk_panel_metrics_v2 import (
    build_payload,
    build_rows,
    overlay_management_confidence,
    scored_terminal,
)


def _promise(fiscal: str, edge: str, ticker: str = "NVDA") -> dict:
    return {
        "ticker": ticker,
        "kind": "promise",
        "nodes": [{"fiscal_period": fiscal, "edge": edge}],
    }


def _goal(fiscal: str, edge: str, ticker: str = "NVDA") -> dict:
    return {
        "ticker": ticker,
        "kind": "goal",
        "nodes": [{"fiscal_period": fiscal, "edge": edge}],
    }


def test_flex_v1_still_delivered() -> None:
    v1_flex_still_delivered()


def test_unresolved_and_still_want_are_not_terminals() -> None:
    assert scored_terminal({"kind": "promise", "nodes": [{"fiscal_period": "FY2025-Q1", "edge": "silent"}]}) is None
    assert scored_terminal({"kind": "goal", "nodes": []}) is None
    assert scored_terminal(_goal("FY2025-Q1", "still-want")) is None
    assert scored_terminal(_promise("FY2025-Q1", "abandoned")) is None


def test_pit_future_miss_does_not_move_earlier_trust() -> None:
    trees = [
        _promise("FY2024-Q4", "delivered"),
        _promise("FY2026-Q3", "missed"),
    ]
    rows = {row["fiscal_period"]: row for row in build_rows(trees, WINDOW) if row["ticker"] == "NVDA"}
    assert rows["FY2024-Q3"]["desk_trust"] is None
    assert rows["FY2024-Q4"]["desk_trust"] == 1.0
    assert rows["FY2024-Q4"]["desk_trust_n"] == 1
    assert rows["FY2026-Q2"]["desk_trust"] == 1.0
    assert rows["FY2026-Q3"]["desk_trust"] == 0.5
    assert rows["FY2026-Q3"]["desk_trust_n"] == 2


def test_goal_hit_does_not_enter_trust() -> None:
    trees = [
        _promise("FY2024-Q4", "delivered"),
        _goal("FY2026-Q1", "hit"),
    ]
    rows = {row["fiscal_period"]: row for row in build_rows(trees, WINDOW) if row["ticker"] == "NVDA"}
    assert rows["FY2026-Q1"]["desk_trust"] == 1.0
    assert rows["FY2026-Q1"]["desk_trust_n"] == 1
    assert rows["FY2026-Q1"]["desk_ambition"] == 1.0
    assert rows["FY2026-Q1"]["desk_ambition_n"] == 1
    assert rows["FY2025-Q4"]["desk_ambition"] is None


def test_overlay_only_fills_management_confidence() -> None:
    metrics = build_rows([_promise("FY2024-Q4", "delivered")], ("FY2024-Q4",))
    joined = overlay_management_confidence(
        [
            {"ticker": "NVDA", "fiscal_period": "FY2024-Q4", "dimension": "management_confidence"},
            {"ticker": "NVDA", "fiscal_period": "FY2024-Q4", "dimension": "demand"},
        ],
        metrics,
    )
    assert joined[0]["desk_trust"] == 1.0
    assert joined[1]["desk_trust"] is None
    assert joined[1]["desk_trust_n"] == 0


def test_refuses_seventeen_aug_stamp() -> None:
    with pytest.raises(SystemExit, match="17 Aug"):
        build_payload({"generated_at": LOCKED_GENERATED_AT, "trees": [], "window": list(WINDOW)})


def test_payload_keeps_nvda_stamp() -> None:
    payload = build_payload(
        {
            "generated_at": NVDA_STAMP,
            "window": list(WINDOW),
            "trees": [_promise("FY2024-Q4", "delivered"), _goal("FY2026-Q1", "hit")],
        }
    )
    assert payload["generated_at"] == NVDA_STAMP
    assert payload["book_end"]["desk_trust"] == 1.0
    assert payload["book_end"]["desk_ambition"] == 1.0
