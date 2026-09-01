"""Read-only harden candidate helpers. No live novelty."""
from __future__ import annotations

from scripts._desk_harden_candidates import excerpt_has_object, later_promise_hits


def test_excerpt_has_object_is_case_insensitive() -> None:
    assert excerpt_has_object("We will launch Flex next quarter.", ["Flex"]) == ["Flex"]
    assert excerpt_has_object("no match here", ["Flex"]) == []


def test_later_promise_hits_skips_same_quarter_and_goals() -> None:
    novelty = {
        "ticker": "ADSK",
        "quarters": [
            {
                "fiscal_period": "FY2022-Q1",
                "novelties": [
                    {
                        "dimension": "competitive_position",
                        "evidence": [
                            {
                                "excerpt": "We want Flex mix.",
                                "verified": True,
                                "status": "verbatim",
                            }
                        ],
                    }
                ],
            },
            {
                "fiscal_period": "FY2022-Q2",
                "novelties": [
                    {
                        "dimension": "competitive_position",
                        "evidence": [
                            {
                                "excerpt": "At the end of September, we will launch Flex.",
                                "verified": True,
                                "status": "verbatim",
                            }
                        ],
                    }
                ],
            },
        ],
    }
    hits = later_promise_hits(
        novelty, ticker="ADSK", after_fiscal="FY2022-Q1", objects=["Flex"]
    )
    assert len(hits) == 1
    assert hits[0]["fiscal_period"] == "FY2022-Q2"
    same = later_promise_hits(
        novelty, ticker="ADSK", after_fiscal="FY2022-Q2", objects=["Flex"]
    )
    assert same == []
