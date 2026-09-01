"""Management transparency ledger. Fixture-only. Not desk_trust."""
from __future__ import annotations

import json
from pathlib import Path

from scripts._desk_transparency_v2 import events_for_book, novelty_periods
from services.earnings_monitor.dashboard.claims_transparency import (
    TRANSPARENCY_STAMP,
    classify_node,
    collapse_ledger,
    expanding_rows,
    implicit_event,
    ledger_rows,
    load_desk_transparency_v2,
    merge_events,
    neglect_caption,
    rate_counts,
    tree_rate_counts,
    typed_events,
)


def _tree(**overrides: object) -> dict:
    item = {
        "ticker": "NVDA",
        "tree_id": "nvda-h20",
        "title": "H20",
        "current_kind": "promise",
        "kind": "promise",
        "clock": "FY2026-Q3",
        "open": True,
        "seed": {"fiscal_period": "FY2025-Q1", "clock": "FY2026-Q3"},
        "nodes": [],
    }
    item.update(overrides)
    return item


def test_typed_silent_due_is_slipped_not_missed() -> None:
    tree = _tree(
        nodes=[
            {"fiscal_period": "FY2026-Q3", "edge": "silent", "excerpt": ""},
            {"fiscal_period": "FY2026-Q4", "edge": "missed", "excerpt": "We missed the H20 window."},
        ]
    )
    events = typed_events(tree)
    assert [row["status"] for row in events] == ["slipped", "addressed"]
    assert events[0]["implicit"] is False
    assert events[1]["edge"] == "missed"


def test_withdrawn_is_not_ignored() -> None:
    assert (
        classify_node({"edge": "dropped", "fiscal_period": "FY2024-Q2"}, clock="FY2024-Q1")
        == "withdrawn"
    )
    assert (
        classify_node({"edge": "abandoned", "fiscal_period": "FY2024-Q2", "excerpt": "we walked"}, clock=None)
        == "withdrawn"
    )


def test_implicit_ignore_only_after_seed() -> None:
    tree = _tree(clock=None, seed={"fiscal_period": "FY2024-Q2"})
    assert implicit_event(tree, "FY2024-Q2", addressed=False) is None
    assert implicit_event(tree, "FY2024-Q3", addressed=False) is None
    addressed = implicit_event(tree, "FY2024-Q4", addressed=True)
    assert addressed is not None
    assert addressed["status"] == "addressed"
    slipped = implicit_event(
        _tree(
            clock="FY2025-Q1",
            seed={"fiscal_period": "FY2024-Q4", "clock": "FY2025-Q1"},
        ),
        "FY2025-Q1",
        addressed=False,
    )
    assert slipped is not None
    assert slipped["status"] == "slipped"


def test_merge_typed_wins_and_closed_tree_stops() -> None:
    tree = _tree(
        open=False,
        nodes=[
            {"fiscal_period": "FY2026-Q3", "edge": "silent"},
            {"fiscal_period": "FY2026-Q4", "edge": "missed", "excerpt": "missed"},
        ],
    )
    events = merge_events(
        tree,
        [
            ("FY2026-Q3", True),
            ("FY2026-Q4", False),
            ("FY2027-Q1", False),
        ],
    )
    by_period = {row["fiscal_period"]: row for row in events}
    assert by_period["FY2026-Q3"]["implicit"] is False
    assert by_period["FY2026-Q3"]["status"] == "slipped"
    assert "FY2027-Q1" not in by_period


def test_withdrawn_stays_out_of_neglect_rate() -> None:
    counts = rate_counts(
        [
            {"status": "addressed"},
            {"status": "ignored"},
            {"status": "slipped"},
            {"status": "withdrawn"},
        ]
    )
    assert counts["n_live"] == 3
    assert counts["n_neglected"] == 2
    assert counts["neglect_rate"] == 2 / 3
    assert counts["n_withdrawn"] == 1
    assert counts["slip_rate"] == 1 / 3
    assert ledger_rows(
        [
            {"status": "addressed", "fiscal_period": "FY2024-Q1"},
            {"status": "ignored", "fiscal_period": "FY2024-Q2"},
            {"status": "withdrawn", "fiscal_period": "FY2024-Q3"},
        ]
    ) == [
        {"status": "ignored", "fiscal_period": "FY2024-Q2"},
        {"status": "withdrawn", "fiscal_period": "FY2024-Q3"},
    ]


def test_empty_live_is_em_dash_not_zero() -> None:
    counts = rate_counts([{"status": "withdrawn"}])
    assert counts["n_live"] == 0
    assert counts["neglect_rate"] is None
    assert "not a 0% neglect rate" in neglect_caption(counts)


def test_expanding_rows_are_point_in_time() -> None:
    events = [
        {"ticker": "NVDA", "fiscal_period": "FY2024-Q1", "status": "addressed"},
        {"ticker": "NVDA", "fiscal_period": "FY2024-Q2", "status": "ignored"},
    ]
    rows = {row["fiscal_period"]: row for row in expanding_rows(events)}
    assert rows["FY2024-Q1"]["neglect_rate"] == 0.0
    assert rows["FY2024-Q2"]["neglect_rate"] == 0.5
    assert rows["FY2024-Q1"]["n_live"] == 1
    assert rows["FY2024-Q2"]["n_live"] == 2


def test_loader_refuses_foreign_stamps(tmp_path: Path) -> None:
    folder = tmp_path / "cross_company" / "json"
    folder.mkdir(parents=True)
    path = folder / "desk_transparency_v2.json"
    path.write_text(
        json.dumps({"generated_at": "2026-08-27T18:02:00+00:00", "books": {}}),
        encoding="utf-8",
    )
    assert load_desk_transparency_v2(tmp_path) is None
    path.write_text(
        json.dumps({"generated_at": "2026-08-17T17:28:40+00:00", "books": {}}),
        encoding="utf-8",
    )
    assert load_desk_transparency_v2(tmp_path) is None
    path.write_text(
        json.dumps({"generated_at": TRANSPARENCY_STAMP, "books": {"nvda_gold_v2": {}}}),
        encoding="utf-8",
    )
    loaded = load_desk_transparency_v2(tmp_path)
    assert loaded is not None
    assert loaded["generated_at"] == TRANSPARENCY_STAMP


def test_tree_slip_is_one_vote_per_tree() -> None:
    events = [
        {"tree_id": "a", "status": "slipped", "fiscal_period": "FY2024-Q1", "clock": "FY2024-Q1"},
        {"tree_id": "a", "status": "slipped", "fiscal_period": "FY2024-Q2", "clock": "FY2024-Q1"},
        {"tree_id": "b", "status": "addressed", "fiscal_period": "FY2024-Q2", "clock": "FY2024-Q2"},
        {"tree_id": "c", "status": "ignored", "fiscal_period": "FY2024-Q2"},
    ]
    trees = tree_rate_counts(events)
    assert trees["n_trees"] == 3
    assert trees["n_trees_slipped"] == 1
    assert trees["n_trees_due"] == 2
    assert trees["tree_slip_rate"] == 0.5
    collapsed = collapse_ledger(
        [
            {
                "tree_id": "a",
                "status": "slipped",
                "fiscal_period": "FY2024-Q1",
                "clock": "FY2024-Q1",
                "implicit": True,
                "ticker": "NVDA",
                "title": "H20",
            },
            {
                "tree_id": "a",
                "status": "slipped",
                "fiscal_period": "FY2024-Q2",
                "clock": "FY2024-Q1",
                "implicit": True,
                "ticker": "NVDA",
                "title": "H20",
            },
            {
                "tree_id": "c",
                "status": "ignored",
                "fiscal_period": "FY2024-Q2",
                "implicit": False,
                "ticker": "NVDA",
                "title": "query",
            },
        ]
    )
    assert len(collapsed) == 2
    slip = next(row for row in collapsed if row["tree_id"] == "a")
    assert slip["n_quarters"] == 2
    assert slip["first_fiscal"] == "FY2024-Q1"
    assert slip["last_fiscal"] == "FY2024-Q2"


def test_implicit_addressed_is_not_a_terminal() -> None:
    event = implicit_event(_tree(), "FY2025-Q2", addressed=True)
    assert event is not None
    assert event["status"] == "addressed"
    assert event["edge"] == "restated"
    assert event["edge"] not in {"delivered", "hit", "missed"}


def test_builder_uses_only_novelty_quarters(monkeypatch) -> None:
    tree = _tree(nodes=[], open=True)
    novelty = {
        "quarters": [
            {"fiscal_period": "FY2025-Q1", "novelties": []},
            {"fiscal_period": "FY2025-Q2", "novelties": []},
        ]
    }
    assert novelty_periods(novelty) == ["FY2025-Q1", "FY2025-Q2"]

    def _no_hit(evidence, objects):
        return None

    monkeypatch.setattr("scripts._desk_transparency_v2.first_object_hit", _no_hit)
    monkeypatch.setattr(
        "scripts._desk_transparency_v2.quarter_for_fiscal",
        lambda view, period: {"fiscal_period": period},
    )
    events = events_for_book([tree], {"NVDA": novelty})
    assert events == []
    due_novelty = {
        "quarters": [
            {"fiscal_period": "FY2025-Q1", "novelties": []},
            {"fiscal_period": "FY2026-Q3", "novelties": []},
        ]
    }
    slipped = events_for_book([tree], {"NVDA": due_novelty})
    assert [row["fiscal_period"] for row in slipped] == ["FY2026-Q3"]
    assert slipped[0]["status"] == "slipped"
    assert slipped[0]["implicit"] is True
