"""Pipeline hook tests. No live novelty_view. No LLM."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from services.earnings_monitor.desk_trees import walk_after_novelty_view


def _book(stamp: str, trees: list[dict]) -> dict:
    return {
        "generated_at": stamp,
        "book_id": "nvda_gold_v2",
        "trees": trees,
    }


def test_hook_skips_missing_book(tmp_path) -> None:
    result = walk_after_novelty_view(
        repo_root=tmp_path,
        ticker="NVDA",
        fiscal_period="FY2027-Q2",
    )
    assert result["status"] == "skipped"
    assert result["reason"] == "no_book"


def test_hook_refuses_v1_stamp(tmp_path) -> None:
    path = (
        tmp_path
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_v2.json"
    )
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(_book("2026-08-17T17:28:40+00:00", [])),
        encoding="utf-8",
    )
    result = walk_after_novelty_view(
        repo_root=tmp_path,
        ticker="NVDA",
        fiscal_period="FY2027-Q2",
    )
    assert result["status"] == "refused"
    assert result["reason"] == "v1_stamp"
    queue_path = (
        tmp_path
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_cue_queue_v2.json"
    )
    assert not queue_path.is_file()


def test_hook_walks_open_tree(tmp_path) -> None:
    root = tmp_path
    book_path = (
        root
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_v2.json"
    )
    novelty_path = (
        root / "Structured Narrative" / "output" / "NVDA" / "json" / "novelty_view.json"
    )
    book_path.parent.mkdir(parents=True)
    novelty_path.parent.mkdir(parents=True)
    tree = {
        "tree_id": "nvda-open",
        "ticker": "NVDA",
        "kind": "promise",
        "beat_id": "x",
        "title": "X",
        "objects": ["Hopper"],
        "open": True,
        "seed": {
            "fiscal_period": "FY2027-Q1",
            "claim_type": "forward_clock",
            "clock": "FY2027-Q4",
            "excerpt": "We will ship more Hopper.",
            "dimension": "competitive_position",
            "status": "verbatim",
        },
        "nodes": [],
        "clock": "FY2027-Q4",
        "state": "open",
        "delivery": "unresolved",
    }
    book_path.write_text(
        json.dumps(_book("2026-08-27T18:02:00+00:00", [tree])),
        encoding="utf-8",
    )
    novelty_path.write_text(
        json.dumps(
            {
                "quarters": [
                    {
                        "fiscal_period": "FY2027-Q2",
                        "novelties": [
                            {
                                "dimension": "competitive_position",
                                "evidence": [
                                    {
                                        "excerpt": "Hopper remains in the mix.",
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
        repo_root=root,
        ticker="NVDA",
        fiscal_period="FY2027-Q2",
        now=datetime(2026, 8, 27, tzinfo=timezone.utc),
    )
    assert result["status"] == "walked"
    assert result["changed"] is True
    updated = json.loads(book_path.read_text(encoding="utf-8"))
    assert updated["generated_at"] == "2026-08-27T18:02:00+00:00"
    assert updated["trees"][0]["nodes"][-1]["edge"] == "restated"
    assert updated["trees"][0]["delivery"] == "unresolved"
    assert result["cue_queue"]["status"] == "written"
    assert result["cue_queue"]["proposals"]["status"] == "written"
    assert result["cue_queue"]["gold_recall"] is None or result["cue_queue"]["gold_recall"] == 1.0
    queue_path = (
        root
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_cue_queue_v2.json"
    )
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert queue["generated_at"] == "2026-08-27T18:02:00+00:00"
    assert "trees" not in queue
    assert updated["trees"][0]["delivery"] == "unresolved"
    assert len(updated["trees"]) == 1
