"""Cue-queue writer. No LLM. No transcripts_raw dump."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from scripts._desk_cue_queue import (
    V1_STAMP,
    build_cue_queue,
    queue_path,
    refuse_stamp,
    write_cue_queue,
)
from scripts._desk_trees_v2 import NVDA_STAMP, SPLIT, WINDOW
from scripts._desk_trees_v2_recall import recall_report


def _novelty() -> dict:
    return {
        "quarters": [
            {
                "fiscal_period": "FY2022-Q2",
                "novelties": [
                    {
                        "dimension": "competitive_position",
                        "evidence": [
                            {
                                "excerpt": "At COMPUTEX, we're going to announce a major product line.",
                                "verified": True,
                                "status": "verbatim",
                            }
                        ],
                    }
                ],
            },
            {
                "fiscal_period": "FY2027-Q2",
                "novelties": [
                    {
                        "dimension": "competitive_position",
                        "evidence": [
                            {
                                "excerpt": "We will ship Groq 3 LPX in volume later this quarter.",
                                "verified": True,
                                "status": "verbatim",
                            }
                        ],
                    }
                ],
            },
        ]
    }


def _trees() -> list[dict]:
    return [
        {
            "seed": {
                "excerpt": "At COMPUTEX, we're going to announce a major product line."
            },
            "nodes": [],
        }
    ]


def test_refuse_v1_stamp() -> None:
    with pytest.raises(SystemExit, match="17 Aug"):
        refuse_stamp(V1_STAMP)


def test_build_queue_keeps_gold_counts_separate() -> None:
    novelty = _novelty()
    trees = _trees()
    gold = recall_report(novelty, trees, WINDOW)
    payload = build_cue_queue(
        book={"generated_at": NVDA_STAMP},
        novelty=novelty,
        trees=trees,
        latest_quarter="FY2027-Q2",
        now=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    assert payload["generated_at"] == NVDA_STAMP
    assert payload["gold"]["split"] == SPLIT
    assert payload["gold"]["n_seedable"] == gold["n_seedable"]
    assert payload["gold"]["n_missed"] == gold["n_missed"]
    assert payload["latest"]["fiscal_period"] == "FY2027-Q2"
    assert payload["latest"]["n_missed"] == 1
    assert payload["n_missed"] == 1
    assert payload["missed"][0]["fiscal_period"] == "FY2027-Q2"


def test_write_queue_refuses_v1(tmp_path) -> None:
    with pytest.raises(SystemExit, match="17 Aug"):
        write_cue_queue(
            repo_root=tmp_path,
            book={"generated_at": V1_STAMP},
            novelty=_novelty(),
            trees=_trees(),
            latest_quarter="FY2027-Q2",
        )
    assert not queue_path(tmp_path).is_file()


def test_build_queue_refuses_transcripts_raw() -> None:
    with pytest.raises(SystemExit, match="transcripts_raw"):
        build_cue_queue(
            book={"generated_at": NVDA_STAMP},
            novelty={"quarters": [], "transcripts_raw": True},
            trees=_trees(),
            latest_quarter="FY2027-Q2",
        )


def test_write_queue_does_not_invent_seeds(tmp_path) -> None:
    book = {"generated_at": NVDA_STAMP, "trees": _trees()}
    written = write_cue_queue(
        repo_root=tmp_path,
        book=book,
        novelty=_novelty(),
        trees=_trees(),
        latest_quarter="FY2027-Q2",
        now=datetime(2026, 8, 28, tzinfo=timezone.utc),
    )
    path = queue_path(tmp_path)
    assert path.is_file()
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["n_missed"] == written["n_missed"]
    assert "trees" not in stored
    assert book["trees"] == _trees()
