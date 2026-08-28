"""Cue-recall guards for the NVIDIA gold catalog."""
from __future__ import annotations

import json

from scripts._desk_trees_v2 import WINDOW
from scripts._desk_trees_v2_nvda import NVDA_TREES
from scripts._desk_trees_v2_recall import (
    classify,
    novelty_path,
    novelty_periods,
    recall_report,
)


def test_rejects_are_not_desk_objects() -> None:
    assert classify(
        "I would expect that we will see a supply-constrained environment "
        "for the vast majority of next year is my guess at the moment."
    ) == "reject"
    assert classify(
        "We have a regular capital strategy process, and we'll go through "
        "that, and we'll make the best judgment about how to use our capital."
    ) == "reject"
    assert classify(
        "Whatever the new administration decides, we will of course "
        "support the administration."
    ) == "reject"
    assert classify(
        "China shipments absent any change in regulations, we believe "
        "that will remain roughly at the current percentage."
    ) == "reject"
    assert classify(
        "Losing access to the China AI accelerator market, which we "
        "believe will grow to nearly $50 billion, would have a material "
        "adverse impact."
    ) == "reject"
    assert classify(
        "We expect to grow revenue by approximately 70% in fiscal 2028. "
        "This is a supply-constrained outlook."
    ) == "reject"
    assert classify(
        "In the quarter, we announced our pending acquisition of Mellanox "
        "for $125 per share in cash representing a total enterprise value "
        "of approximately $6.9 billion, which we believe will strengthen "
        "our strategic position in data center."
    ) == "reject"
    assert classify(
        "And with our pending acquisition of Arm, the company that builds "
        "the world's most popular CPU, we will create the computing "
        "company for the age of AI."
    ) == "reject"
    assert classify(
        "We announced DRIVE PX Pegasus, the world's first AI computer for "
        "enabling Level 5 driverless vehicles. Pegasus will deliver over "
        "320 trillion operations per second."
    ) == "reject"
    assert classify(
        "The delta from Q4 to Q1 is, we only have a partial part of "
        "recognition from the Intel, and that stops in the middle of March. "
        "So as we move forward as well, going into Q2, we will also have "
        "the absence of what we had in Q1 moving to Q2."
    ) == "reject"


def test_printed_growth_outlook_is_guidance() -> None:
    assert classify(
        "Consistent with our outlook Mellanox had a sequential decline. "
        "We expect to return to sequential growth in Q1 driven by strong "
        "demand for our high speed networking products."
    ) == "guidance"
    assert classify(
        "We expect to continue to grow as we move into the second half "
        "of the year as well for gaming."
    ) == "guidance"


def test_computex_announce_is_a_promise_cue() -> None:
    assert classify(
        "At COMPUTEX, we're going to announce a major product line "
        "for this segment."
    ) == "promise"


def test_gold_cue_recall_is_complete() -> None:
    path = novelty_path()
    if not path.is_file():
        return
    novelty = json.loads(path.read_text(encoding="utf-8"))
    report = recall_report(novelty, NVDA_TREES)
    assert report["n_seedable"] >= 1
    assert report["n_missed"] == 0
    assert report["recall"] == 1.0
    full = recall_report(novelty, NVDA_TREES, novelty_periods(novelty))
    gold_again = recall_report(novelty, NVDA_TREES, WINDOW)
    assert gold_again["n_seedable"] == report["n_seedable"]
    assert gold_again["n_covered"] == report["n_covered"]
    assert gold_again["n_missed"] == 0
    assert gold_again["recall"] == 1.0
    assert full["n_seedable"] >= report["n_seedable"]
    assert full["n_missed"] == 0
    assert full["recall"] == 1.0
