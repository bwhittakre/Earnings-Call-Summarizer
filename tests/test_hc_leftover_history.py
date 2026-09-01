"""Fixture tests for leftover-history overnight prep. Does not score."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
if str(SN) not in sys.path:
    sys.path.insert(0, str(SN))

from evaluate_narrative_signals import (
    HEALTHCARE_EVAL_OUTPUT_TAG,
    LOCKED_TECH_EVAL_GENERATED_AT,
    refuse_locked_tech_eval_overwrite,
)
from scripts._hc_leftover_history import (
    HEALTHCARE_TAG,
    LEFTOVERS,
    LLOYDS_ISIN,
    TWO_Q_OUTPUT,
    leftover_plan,
    overlay_is_expanded,
)


def test_overlay_is_expanded_two_q() -> None:
    assert overlay_is_expanded({"output_quarters": list(TWO_Q_OUTPUT)}) is False
    assert overlay_is_expanded({"output_quarters": ["FY2018-Q2", *TWO_Q_OUTPUT]}) is True


def test_dry_run_plan_does_not_claim_score() -> None:
    plan = leftover_plan()
    assert plan["dry_run"] is True
    assert plan["healthcare_output_tag"] == HEALTHCARE_TAG == HEALTHCARE_EVAL_OUTPUT_TAG
    assert "--force" not in plan["score_command"]
    assert "run_onboard" not in plan["score_command"]
    assert HEALTHCARE_TAG in plan["stamp_command"]
    assert "--output-tag" in plan["stamp_command"]
    assert [n["ticker"] for n in plan["names"]] == list(LEFTOVERS)
    for row in plan["names"]:
        assert row["isin"] != LLOYDS_ISIN
        # expanded / current_output are data-state checks; overlays were
        # expanded in the HC overnight run.  The structural plan assertions
        # above still guard against unsafe changes to the dry-run command.


def test_refuse_locked_untagged_overwrite(tmp_path: Path) -> None:
    dest = tmp_path / "narrative_signal_eval.json"
    dest.write_text(
        json.dumps({"generated_at": LOCKED_TECH_EVAL_GENERATED_AT}),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit, match="refuses untagged overwrite"):
        refuse_locked_tech_eval_overwrite(dest, output_tag=None)
    refuse_locked_tech_eval_overwrite(dest, output_tag=HEALTHCARE_EVAL_OUTPUT_TAG)
    refuse_locked_tech_eval_overwrite(dest, output_tag=None, replace_locked=True)


def test_refuse_allows_missing_or_other_stamp(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    refuse_locked_tech_eval_overwrite(missing, output_tag=None)
    other = tmp_path / "other.json"
    other.write_text(json.dumps({"generated_at": "2026-01-01T00:00:00+00:00"}), encoding="utf-8")
    refuse_locked_tech_eval_overwrite(other, output_tag=None)
