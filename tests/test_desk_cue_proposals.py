"""Gated cue proposals. Candidates only. No tree insert. No LLM."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts._desk_cue_proposals import (
    build_cue_proposals,
    propose_from_missed,
    proposer_gate,
    write_cue_proposals,
)
from scripts._desk_cue_queue import V1_STAMP
from scripts._desk_trees_v2 import NVDA_STAMP


def _book() -> dict:
    return {"generated_at": NVDA_STAMP, "trees": [{"tree_id": "nvda-existing"}]}


def _queue(*, recall: float = 1.0, missed: list | None = None) -> dict:
    return {
        "generated_at": NVDA_STAMP,
        "missed": missed or [],
        "gold": {"recall": recall, "n_missed": 0},
    }


def test_gate_requires_gold_recall() -> None:
    allowed, reason = proposer_gate(_queue(recall=0.8))
    assert allowed is False
    assert reason == "gold_recall"
    allowed, reason = proposer_gate(_queue(recall=1.0))
    assert allowed is True
    assert reason == "ok"


def test_empty_queue_writes_zero_proposals(tmp_path) -> None:
    book = _book()
    payload = write_cue_proposals(
        repo_root=tmp_path,
        book=book,
        queue=_queue(),
        now=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    assert payload["n_proposals"] == 0
    assert payload["gate"]["allowed"] is True
    assert book["trees"] == [{"tree_id": "nvda-existing"}]


def test_missed_row_becomes_candidate_not_a_tree() -> None:
    book = _book()
    payload = build_cue_proposals(
        book=book,
        queue=_queue(
            missed=[
                {
                    "fiscal_period": "FY2027-Q3",
                    "class": "promise",
                    "dimension": "competitive_position",
                    "excerpt": "We will ship the named product in FY2027-Q4.",
                }
            ]
        ),
        now=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    assert payload["n_proposals"] == 1
    row = payload["proposals"][0]
    assert row["kind"] == "promise"
    assert row["clock"] == "FY2027-Q4"
    assert row["status"] == "candidate"
    assert row["tree_id"].startswith("nvda-proposed-")
    assert book["trees"] == [{"tree_id": "nvda-existing"}]


def test_refuses_v1_stamp() -> None:
    with pytest.raises(SystemExit, match="17 Aug"):
        build_cue_proposals(
            book={"generated_at": V1_STAMP},
            queue=_queue(),
        )


def test_closed_gate_writes_no_candidates() -> None:
    payload = build_cue_proposals(
        book=_book(),
        queue=_queue(
            recall=0.5,
            missed=[
                {
                    "fiscal_period": "FY2027-Q3",
                    "class": "promise",
                    "excerpt": "We will ship something.",
                }
            ],
        ),
    )
    assert payload["gate"]["allowed"] is False
    assert payload["n_proposals"] == 0
