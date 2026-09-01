"""Healthcare desk book. Not NVIDIA gold. Not tech ops. No LLM."""
from __future__ import annotations

import json

import pytest

from scripts._desk_trees_v2 import BUCKETS, NVDA_STAMP, build_ops_book
from scripts._desk_trees_v2_hc import (
    HC_BOOK_ID,
    HC_STAMP,
    HC_TICKERS,
    assert_hc_stamp,
)
from scripts._desk_trees_v2_hc_catalogs import HC_TREES
from scripts._desk_trees_v2_ops import OPS_STAMP
from services.earnings_monitor.dashboard.claims_trees import (
    _BOOK_HC,
    load_desk_trees_hc_v2,
)
from services.earnings_monitor.desk_trees import walk_after_novelty_view


def test_hc_book_refuses_gold_and_ops_stamps() -> None:
    with pytest.raises(SystemExit, match="NVIDIA gold"):
        assert_hc_stamp(NVDA_STAMP)
    with pytest.raises(SystemExit, match="tech ops"):
        assert_hc_stamp(OPS_STAMP)


def test_hc_book_builds_empty() -> None:
    payload = build_ops_book(
        [],
        {},
        generated_at=HC_STAMP,
        verify_excerpts=False,
        book_id=HC_BOOK_ID,
        split="hc-ops-novelty-present",
    )
    assert payload["book_id"] == "desk_hc_v2"
    assert payload["generated_at"] == HC_STAMP
    assert payload["n_trees"] == 0
    assert "NVDA" not in HC_TICKERS
    assert len(HC_TICKERS) == 20


def test_hc_catalog_skips_gold_and_tech() -> None:
    tickers = {str(tree["ticker"]) for tree in HC_TREES}
    assert "NVDA" not in tickers
    assert "MSFT" not in tickers
    assert set(HC_TICKERS) == tickers
    by_id = {str(tree["tree_id"]): tree for tree in HC_TREES}
    assert {tree.get("bucket") for tree in HC_TREES} <= set(BUCKETS)
    assert all(tree.get("bucket") for tree in HC_TREES)
    assert by_id["tmo-2019-guidance-january"]["bucket"] == "guidance"
    assert by_id["ci-ma-growth-10"]["bucket"] == "demand"
    assert by_id["lly-dividend-december"]["bucket"] == "capital_allocation"
    assert by_id["abbv-humira-ip-2022"]["bucket"] == "macro_regulatory_risk"
    assert any(
        node.get("edge") == "delivered"
        for node in by_id["isrg-davinci-x"].get("nodes") or ()
    )
    assert not any(
        node.get("edge") == "delivered"
        for node in by_id["lly-dividend-december"].get("nodes") or ()
    )
    assert all(
        tree.get("delivery") != "delivered" and tree.get("goal_outcome") != "hit"
        for tree in HC_TREES
    )


def test_hc_loader_refuses_gold(tmp_path) -> None:
    folder = tmp_path / "cross_company" / "json"
    folder.mkdir(parents=True)
    (folder / "desk_trees_hc_v2.json").write_text(
        json.dumps({"generated_at": NVDA_STAMP, "trees": []}),
        encoding="utf-8",
    )
    assert load_desk_trees_hc_v2(tmp_path / "cross_company") is None
    (folder / "desk_trees_hc_v2.json").write_text(
        json.dumps({"generated_at": HC_STAMP, "book_id": _BOOK_HC, "trees": []}),
        encoding="utf-8",
    )
    loaded = load_desk_trees_hc_v2(tmp_path / "cross_company")
    assert loaded is not None
    assert loaded["generated_at"] == HC_STAMP


def test_hook_healthcare_writes_hc_queue_not_gold(tmp_path) -> None:
    gold_path = (
        tmp_path
        / "Structured Narrative"
        / "output"
        / "cross_company"
        / "json"
        / "desk_trees_v2.json"
    )
    novelty_path = (
        tmp_path / "Structured Narrative" / "output" / "LLY" / "json" / "novelty_view.json"
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
                        "fiscal_period": "FY2026-Q2",
                        "novelties": [
                            {
                                "dimension": "competitive_position",
                                "evidence": [
                                    {
                                        "excerpt": (
                                            "We will expand Mounjaro manufacturing "
                                            "for named launch markets."
                                        ),
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
        ticker="LLY",
        fiscal_period="FY2026-Q2",
    )
    assert result["status"] == "walked"
    assert gold_path.read_text(encoding="utf-8") == gold_before
    queue_path = gold_path.parent / "desk_cue_queue_v2_LLY.json"
    assert queue_path.is_file()
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert queue["generated_at"] == HC_STAMP
    assert queue["gold"] is None
    assert queue["n_missed"] >= 1
    assert "trees" not in queue
    ops_queue = gold_path.parent / "desk_cue_queue_v2.json"
    assert not ops_queue.is_file() or json.loads(ops_queue.read_text(encoding="utf-8")).get(
        "generated_at"
    ) != HC_STAMP
