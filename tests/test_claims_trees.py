"""Pure helpers for the Claims Trees Roz page. No Streamlit."""
from __future__ import annotations

import json

from services.earnings_monitor.dashboard.claims_trees import (
    _BOOK_HC,
    _BOOK_NVDA,
    _BOOK_OPS,
    _NVDA_STAMP,
    _V1_STAMP,
    attach_metrics_to_backdrop,
    clock_board,
    filter_trees_to_universe,
    format_n_rate,
    format_rate,
    last_cited_fiscal,
    latest_scored_fiscal,
    load_desk_cue_queue_v2,
    scored_rate_caption,
    show_trailing_credibility,
    suggested_book,
    load_desk_panel_metrics_v2,
    load_desk_trees_v2,
    tree_node_rows,
)


def test_format_rate_em_dash_when_unresolved() -> None:
    assert format_rate(None) == "—"
    assert format_rate(0.8) == "80%"
    assert format_n_rate(None, 0, 0) == "—"
    assert format_n_rate(0.6, 5, 3) == "60% (3/5)"


def test_filter_trees_respects_universe() -> None:
    trees = [
        {"ticker": "NVDA", "title": "a"},
        {"ticker": "ADSK", "title": "b"},
    ]
    assert [tree["ticker"] for tree in filter_trees_to_universe(trees, ["NVDA"])] == [
        "NVDA"
    ]


def test_tree_node_rows_start_with_seed() -> None:
    rows = tree_node_rows(
        {
            "seed": {
                "fiscal_period": "FY2025-Q1",
                "excerpt": "seed",
                "citation": "c1",
                "clock": "FY2025-Q4",
            },
            "nodes": [
                {
                    "fiscal_period": "FY2025-Q2",
                    "edge": "silent",
                    "excerpt": None,
                    "slipped": False,
                }
            ],
        }
    )
    assert rows[0]["edge"] == "seed"
    assert rows[1]["edge"] == "silent"
    assert last_cited_fiscal({"seed": {"fiscal_period": "FY2025-Q1"}, "nodes": rows[1:]})


def test_loader_refuses_v1_stamp(tmp_path) -> None:
    folder = tmp_path / "cross_company" / "json"
    folder.mkdir(parents=True)
    (folder / "desk_trees_v2.json").write_text(
        json.dumps({"generated_at": _V1_STAMP, "trees": []}),
        encoding="utf-8",
    )
    assert load_desk_trees_v2(tmp_path / "cross_company") is None
    (folder / "desk_trees_v2.json").write_text(
        json.dumps({"generated_at": _NVDA_STAMP, "book_id": "nvda_gold_v2", "trees": []}),
        encoding="utf-8",
    )
    loaded = load_desk_trees_v2(tmp_path / "cross_company")
    assert loaded is not None
    assert loaded["generated_at"] == _NVDA_STAMP


def test_metrics_loader_refuses_v1_stamp(tmp_path) -> None:
    folder = tmp_path / "cross_company" / "json"
    folder.mkdir(parents=True)
    (folder / "desk_panel_metrics_v2.json").write_text(
        json.dumps({"generated_at": _V1_STAMP, "rows": []}),
        encoding="utf-8",
    )
    assert load_desk_panel_metrics_v2(tmp_path / "cross_company") is None


def test_attach_metrics_to_backdrop() -> None:
    backdrop = [{"fiscal_period": "FY2024-Q4", "role": "seed"}]
    attached = attach_metrics_to_backdrop(
        backdrop,
        {"FY2024-Q4": {"desk_trust": 1.0, "desk_trust_n": 1, "desk_ambition": None, "desk_ambition_n": 0}},
    )
    assert attached[0]["desk_trust"] == 1.0
    assert attached[0]["desk_ambition"] is None


def test_clock_board_slipped_vs_no_clock() -> None:
    trees = [
        {
            "tree_id": "due-silent",
            "ticker": "NVDA",
            "title": "Due silent",
            "kind": "promise",
            "open": True,
            "clock": "FY2026-Q4",
            "slipped": True,
            "state": "open",
        },
        {
            "tree_id": "due-restated",
            "ticker": "NVDA",
            "title": "Clock due restated",
            "kind": "promise",
            "open": True,
            "clock": "FY2026-Q4",
            "slipped": False,
            "state": "open",
        },
        {
            "tree_id": "someday",
            "ticker": "NVDA",
            "title": "Every query",
            "kind": "goal",
            "open": True,
            "clock": None,
            "slipped": False,
            "state": "still-want",
        },
        {
            "tree_id": "future",
            "ticker": "NVDA",
            "title": "Next year",
            "kind": "promise",
            "open": True,
            "clock": "FY2027-Q4",
            "slipped": False,
            "state": "open",
        },
        {
            "tree_id": "closed",
            "ticker": "NVDA",
            "title": "Delivered",
            "kind": "promise",
            "open": False,
            "clock": "FY2024-Q2",
            "slipped": False,
            "state": "delivered",
        },
    ]
    board = clock_board(trees, "FY2027-Q2")
    assert [row["tree_id"] for row in board["slipped"]] == ["due-silent"]
    assert [row["tree_id"] for row in board["due"]] == ["due-restated"]
    assert [row["tree_id"] for row in board["open_no_clock"]] == ["someday"]


def test_latest_scored_fiscal_prefers_queue() -> None:
    assert (
        latest_scored_fiscal(
            {"walked_trigger": "NVDA:FY2027-Q1"},
            {"latest_quarter": "FY2027-Q2"},
        )
        == "FY2027-Q2"
    )


def test_suggested_book_follows_sector() -> None:
    books = [_BOOK_NVDA, _BOOK_OPS, _BOOK_HC]
    assert suggested_book("healthcare_large_cap", books) == _BOOK_HC
    assert suggested_book("xlk_tech", books) == _BOOK_OPS
    assert suggested_book("All Companies", books) == _BOOK_NVDA
    assert suggested_book("Custom List", books, ["LLY", "JNJ"]) == _BOOK_HC
    assert suggested_book("Custom List", books, ["NVDA"]) == _BOOK_NVDA
    assert suggested_book("Custom List", books, ["MSFT", "CRM"]) == _BOOK_OPS


def test_honest_rate_caption_and_gold_only_trust() -> None:
    assert "not a 0%" in scored_rate_caption(0, "promises")
    assert scored_rate_caption(1, "promises").startswith("Scored")
    assert show_trailing_credibility(_BOOK_NVDA) is True
    assert show_trailing_credibility(_BOOK_OPS) is False
    assert show_trailing_credibility(_BOOK_HC) is False


def test_queue_loader_refuses_v1_stamp(tmp_path) -> None:
    folder = tmp_path / "cross_company" / "json"
    folder.mkdir(parents=True)
    (folder / "desk_cue_queue_v2.json").write_text(
        json.dumps({"generated_at": _V1_STAMP, "missed": []}),
        encoding="utf-8",
    )
    assert load_desk_cue_queue_v2(tmp_path / "cross_company") is None
