"""Operational desk book. Not NVIDIA gold. No LLM."""
from __future__ import annotations

import json

import pytest

from scripts._desk_trees_v2 import NVDA_STAMP, build_ops_book
from scripts._desk_trees_v2_ops import OPS_STAMP, assert_ops_stamp
from services.earnings_monitor.dashboard.claims_trees import (
    _BOOK_OPS,
    load_desk_trees_ops_v2,
)
from services.earnings_monitor.desk_trees import walk_after_novelty_view


def test_ops_book_refuses_gold_stamp() -> None:
    with pytest.raises(SystemExit, match="NVIDIA gold"):
        assert_ops_stamp(NVDA_STAMP)
    with pytest.raises(SystemExit, match="NVIDIA gold"):
        build_ops_book([], {}, generated_at=NVDA_STAMP)


def test_ops_book_builds_empty() -> None:
    payload = build_ops_book([], {}, generated_at=OPS_STAMP, verify_excerpts=False)
    assert payload["book_id"] == "desk_ops_v2"
    assert payload["generated_at"] == OPS_STAMP
    assert payload["n_trees"] == 0
    assert payload["trees"] == []


def test_ops_loader_refuses_gold(tmp_path) -> None:
    folder = tmp_path / "cross_company" / "json"
    folder.mkdir(parents=True)
    (folder / "desk_trees_ops_v2.json").write_text(
        json.dumps({"generated_at": NVDA_STAMP, "trees": []}),
        encoding="utf-8",
    )
    assert load_desk_trees_ops_v2(tmp_path / "cross_company") is None
    (folder / "desk_trees_ops_v2.json").write_text(
        json.dumps({"generated_at": OPS_STAMP, "book_id": _BOOK_OPS, "trees": []}),
        encoding="utf-8",
    )
    loaded = load_desk_trees_ops_v2(tmp_path / "cross_company")
    assert loaded is not None
    assert loaded["generated_at"] == OPS_STAMP


def test_hook_non_nvda_writes_ops_queue_not_gold(tmp_path) -> None:
    gold_path = (
        tmp_path
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_v2.json"
    )
    novelty_path = (
        tmp_path / "Structured Narrative" / "output" / "MSFT" / "json" / "novelty_view.json"
    )
    gold_path.parent.mkdir(parents=True)
    novelty_path.parent.mkdir(parents=True)
    gold_path.write_text(
        json.dumps({"generated_at": NVDA_STAMP, "book_id": "nvda_gold_v2", "trees": []}),
        encoding="utf-8",
    )
    gold_before = gold_path.read_text(encoding="utf-8")
    novelty_path.write_text(
        json.dumps(
            {
                "quarters": [
                    {
                        "fiscal_period": "FY2026-Q4",
                        "novelties": [
                            {
                                "dimension": "competitive_position",
                                "evidence": [
                                    {
                                        "excerpt": "We will ship Azure Local to named customers.",
                                        "verified": True,
                                        "status": "verbatim",
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    result = walk_after_novelty_view(
        repo_root=tmp_path,
        ticker="MSFT",
        fiscal_period="FY2026-Q4",
    )
    assert result["status"] == "walked"
    assert gold_path.read_text(encoding="utf-8") == gold_before
    queue_path = gold_path.parent / "desk_cue_queue_v2_MSFT.json"
    assert queue_path.is_file()
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert queue["generated_at"] == OPS_STAMP
    assert queue["gold"] is None
    assert queue["n_missed"] >= 1
    assert "trees" not in queue
