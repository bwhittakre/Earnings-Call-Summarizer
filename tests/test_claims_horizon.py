"""Horizon series. Slipped is a series miss. Tree delivery stays unresolved."""
from __future__ import annotations

from services.earnings_monitor.dashboard.claims_horizon import (
    collect_horizon_events,
    fiscal_span,
    horizon_event,
    horizon_series,
    rate_from_events,
)


def _slipped_tree() -> dict:
    return {
        "tree_id": "due-silent",
        "ticker": "NVDA",
        "kind": "promise",
        "clock": "FY2022-Q4",
        "slipped": True,
        "state": "open",
        "delivery": "unresolved",
        "seed": {"fiscal_period": "FY2022-Q3", "clock": "FY2022-Q4"},
        "nodes": [
            {
                "fiscal_period": "FY2026-Q2",
                "edge": "silent",
                "excerpt": None,
            }
        ],
    }


def _delivered_tree() -> dict:
    return {
        "tree_id": "on-time",
        "ticker": "NVDA",
        "kind": "promise",
        "clock": "FY2022-Q4",
        "slipped": False,
        "state": "delivered",
        "delivery": "delivered",
        "seed": {"fiscal_period": "FY2022-Q3", "clock": "FY2022-Q4"},
        "nodes": [
            {
                "fiscal_period": "FY2022-Q4",
                "edge": "delivered",
                "excerpt": "We shipped it.",
            }
        ],
    }


def _long_clock_tree() -> dict:
    return {
        "tree_id": "three-q",
        "ticker": "NVDA",
        "kind": "promise",
        "clock": "FY2023-Q1",
        "slipped": False,
        "state": "delivered",
        "delivery": "delivered",
        "seed": {"fiscal_period": "FY2022-Q2", "clock": "FY2023-Q1"},
        "nodes": [
            {
                "fiscal_period": "FY2023-Q1",
                "edge": "delivered",
                "excerpt": "Done.",
            }
        ],
    }


def test_slip_miss_at_clock_does_not_rewrite_delivery() -> None:
    tree = _slipped_tree()
    event = horizon_event(tree, horizon=1)
    assert event is not None
    assert event["event_fiscal"] == "FY2022-Q4"
    assert event["result"] == "fail"
    assert tree["delivery"] == "unresolved"


def test_typed_delivered_at_clock_is_success() -> None:
    event = horizon_event(_delivered_tree(), horizon=1)
    assert event is not None
    assert event["result"] == "success"
    assert event["event_fiscal"] == "FY2022-Q4"


def test_overdue_tree_does_not_reenter_next_quarter() -> None:
    events = collect_horizon_events([_slipped_tree()], horizon=1)
    assert [event["event_fiscal"] for event in events] == ["FY2022-Q4"]
    series = horizon_series(
        [_slipped_tree()],
        ["FY2022-Q4", "FY2023-Q1"],
        horizon=1,
    )
    assert series[0]["horizon_quarter_n"] == 1
    assert series[0]["horizon_quarter_rate"] == 0.0
    assert series[1]["horizon_quarter_n"] == 0
    assert series[1]["horizon_quarter_rate"] is None
    assert series[1]["horizon_cum_n"] == 1
    assert series[1]["horizon_cum_rate"] == 0.0


def test_horizon_1q_drops_3q_clock_all_keeps_it() -> None:
    tree = _long_clock_tree()
    assert horizon_event(tree, horizon=1) is None
    assert horizon_event(tree, horizon="1Q") is None
    kept = horizon_event(tree, horizon="all")
    assert kept is not None
    assert kept["result"] == "success"
    assert horizon_event(tree, horizon=4) is not None


def test_window_ignores_later_terminal() -> None:
    late = {
        "tree_id": "late-2024",
        "ticker": "NVDA",
        "kind": "promise",
        "clock": "FY2024-Q2",
        "slipped": False,
        "state": "missed",
        "delivery": "missed",
        "seed": {"fiscal_period": "FY2024-Q1", "clock": "FY2024-Q2"},
        "nodes": [
            {
                "fiscal_period": "FY2024-Q2",
                "edge": "missed",
                "excerpt": "It missed.",
            }
        ],
    }
    early = _delivered_tree()
    windowed = collect_horizon_events(
        [early, late],
        horizon="all",
        window=("FY2016-Q1", "FY2019-Q4"),
    )
    assert windowed == []
    in_2016_2022 = collect_horizon_events(
        [early, late],
        horizon="all",
        window=("FY2016-Q1", "FY2022-Q4"),
    )
    assert [event["tree_id"] for event in in_2016_2022] == ["on-time"]
    rate = rate_from_events(in_2016_2022)
    assert rate["yes"] == 1
    assert rate["n"] == 1


def test_fiscal_span_is_inclusive() -> None:
    assert fiscal_span("FY2022-Q3", "FY2023-Q1") == [
        "FY2022-Q3",
        "FY2022-Q4",
        "FY2023-Q1",
    ]


def test_no_clock_tree_is_excluded() -> None:
    tree = {
        "tree_id": "someday",
        "ticker": "NVDA",
        "kind": "goal",
        "clock": None,
        "slipped": False,
        "state": "still-want",
        "goal_outcome": "still-want",
        "seed": {"fiscal_period": "FY2022-Q2", "clock": None},
        "nodes": [],
    }
    assert horizon_event(tree, horizon="all") is None
