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
    conversion_caption,
    conversion_from_trees,
    filter_trees_to_bucket,
    filter_trees_to_universe,
    group_trees_by_bucket,
    format_n_rate,
    format_rate,
    last_cited_fiscal,
    latest_scored_fiscal,
    load_desk_cue_queue_v2,
    node_edge_label,
    scored_rate_caption,
    show_trailing_credibility,
    suggested_book,
    load_desk_panel_metrics_v2,
    load_desk_trees_v2,
    tree_kind_label,
    tree_node_rows,
    workshop_book_entry,
    workshop_bundle,
    workshop_horizon_events,
)
from scripts._desk_trees_workshop_html import build_workshop_html


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


def test_filter_and_group_trees_by_bucket() -> None:
    trees = [
        {"ticker": "CRM", "bucket": "earnings_power", "title": "20b"},
        {"ticker": "AAPL", "bucket": "capital_allocation", "title": "cash"},
        {"ticker": "NVDA", "title": "gold"},
    ]
    assert [tree["ticker"] for tree in filter_trees_to_bucket(trees, "all")] == [
        "CRM",
        "AAPL",
        "NVDA",
    ]
    assert [tree["ticker"] for tree in filter_trees_to_bucket(trees, "demand")] == []
    assert [
        tree["ticker"] for tree in filter_trees_to_bucket(trees, "earnings_power")
    ] == ["CRM"]
    assert [tree["ticker"] for tree in filter_trees_to_bucket(trees, "unbucketed")] == [
        "NVDA"
    ]
    grouped = group_trees_by_bucket(trees)
    keys = [key for key, _ in grouped]
    assert keys == ["earnings_power", "capital_allocation", None]


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
    assert suggested_book("independent", books) == _BOOK_HC
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


def test_conversion_caption_and_kind_labels() -> None:
    empty = conversion_from_trees([])
    assert empty["harden_rate"] is None
    assert "not a 0%" in conversion_caption(empty)
    trees = [
        {"kind": "goal", "goal_outcome": "still-want"},
        {
            "kind": "goal",
            "goal_outcome": "became-promise",
            "kind_label": "promise (was goal)",
        },
    ]
    counts = conversion_from_trees(trees)
    assert counts["n_goals"] == 2
    assert counts["n_became_promise"] == 1
    assert "1 of 2" in conversion_caption(counts)
    assert tree_kind_label(trees[1]) == "promise (was goal)"
    assert node_edge_label({"edge": "harden-to-promise"}) == "became a promise"


def test_queue_loader_refuses_v1_stamp(tmp_path) -> None:
    folder = tmp_path / "cross_company" / "json"
    folder.mkdir(parents=True)
    (folder / "desk_cue_queue_v2.json").write_text(
        json.dumps({"generated_at": _V1_STAMP, "missed": []}),
        encoding="utf-8",
    )
    assert load_desk_cue_queue_v2(tmp_path / "cross_company") is None


def test_workshop_book_uses_shared_rates() -> None:
    payload = {
        "caption": "ops",
        "generated_at": "2026-08-31T14:18:00+00:00",
        "split": "tech-ops-novelty-present",
        "calendar": "per-ticker",
        "window": [],
        "deliver_rates": {"book": {"deliver_rate": None, "n_scoreable": 0, "delivered": 0}},
        "hit_rates": {"book": {"hit_rate": None, "n_scoreable": 0, "hit": 0}},
        "trees": [
            {
                "ticker": "CRM",
                "kind": "goal",
                "bucket": "earnings_power",
                "title": "20b",
                "open": True,
                "seed": {"fiscal_period": "FY2017-Q3", "excerpt": "next goal, $20 billion."},
                "nodes": [],
            }
        ],
    }
    entry = workshop_book_entry(_BOOK_OPS, payload, None)
    assert entry is not None
    assert entry["conversion"]["n_goals"] == 1
    assert entry["quotes"][0]["role"] == "seed"
    assert entry["horizon_events"] == workshop_horizon_events(payload["trees"])


def test_workshop_html_mirrors_roz_copy() -> None:
    html = build_workshop_html(
        {
            "surface": "claims_trees",
            "title": "Claims Desk",
            "subtitle": "Workshop for the Roz Claims Trees desk.",
            "books": {},
            "book_order": [],
            "default_book": _BOOK_NVDA,
            "labels": {},
            "metrics": None,
            "buckets": ["demand"],
            "bucket_labels": {"demand": "Demand"},
            "horizon_choices": ["1Q", "all"],
            "bucket_filter_choices": ["all", "demand", "unbucketed"],
        }
    )
    assert "<title>Claims Desk</title>" in html
    assert "Became a promise" in html
    assert "Management transparency" in html
    assert "Due-clock slip rate" in html
    assert "The neglect ledger above scores later calls that did not take up a prior claim." in html
    assert "Bucket is the claim theme" in html
    assert "This is not the locked gold 6/7 desk_trust" in html
    assert "Do not auto-seed" in html
    assert "Expiration means it was never followed up" in html
    assert "Known-delivered" in html
    assert "This is what we know has been delivered" in html
    assert "Quant cross-check" in html
    assert "Clocked trees check at the clock" in html
    assert "id=\"known-delivered\"" in html
    assert "id=\"quant\"" in html


def test_workshop_bundle_loads_recognized_books() -> None:
    bundle = workshop_bundle()
    if not bundle["books"]:
        return
    assert bundle["surface"] == "claims_trees"
    assert set(bundle["books"]) <= {_BOOK_NVDA, _BOOK_OPS, _BOOK_HC}
    assert bundle["title"] == "Claims Desk"
    assert "transparency" in bundle
    assert "quant" in bundle
    assert bundle.get("expire_caption")
    assert "Expiration means" in str(bundle.get("expire_caption"))
    for entry in bundle["books"].values():
        assert "known_delivered" in entry
