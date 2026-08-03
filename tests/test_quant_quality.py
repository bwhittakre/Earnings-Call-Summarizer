"""Tests for consensus usability gates and dimension quality flags."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SN = Path(__file__).resolve().parents[1] / "Structured Narrative"
if str(SN) not in sys.path:
    sys.path.insert(0, str(SN))

from quant_quality import (  # noqa: E402
    FLAG_MEMBER_SUPPRESSED,
    FLAG_NEAR_ZERO_CONSENSUS,
    FLAG_SPARSE_DIMENSION,
    consensus_usable,
    dimension_quality_flags,
    flags_to_storage,
    pct_fields_for_consensus,
    quality_ok,
)
from narrative_zscore import (  # noqa: E402
    DIMENSIONS,
    SURPRISE_ROLE,
    apply_consensus_gates,
    build_dimension_scores,
    build_enriched,
)


def test_mu_like_gross_margin_consensus_not_usable():
    # MU FY2024-Q1 measure 27: actual 37, consensus ≈ -0.68
    assert consensus_usable(-0.67957, 37.0, 27) is False


def test_normal_eps_consensus_usable():
    assert consensus_usable(1.15, 1.20, 9) is True


def test_pct_fields_suppress_near_zero_consensus():
    fields = pct_fields_for_consensus(
        surprise=37.67957,
        revision=0.0,
        pre_mean=-0.67957,
        actual=37.0,
        measure=27,
    )
    assert fields["earnings_surprise_pct"] is None
    assert fields["fwd_estimate_revision_pct"] is None
    assert fields["pct_surprise_usable"] is False
    assert fields["near_zero_consensus"] is True


def test_pct_fields_compute_when_usable():
    fields = pct_fields_for_consensus(
        surprise=0.05,
        revision=0.01,
        pre_mean=1.0,
        actual=1.05,
        measure=9,
    )
    assert fields["earnings_surprise_pct"] == pytest.approx(0.05)
    assert fields["fwd_estimate_revision_pct"] == pytest.approx(0.01)
    assert fields["pct_surprise_usable"] is True
    assert fields["near_zero_consensus"] is False


def test_dimension_flags_mark_suppressed_and_sparse():
    flags = dimension_quality_flags(
        member_zs_clean=[0.1, None, None],
        member_near_zero=[False, True, False],
    )
    assert FLAG_SPARSE_DIMENSION in flags
    assert FLAG_MEMBER_SUPPRESSED in flags
    assert FLAG_NEAR_ZERO_CONSENSUS in flags
    assert quality_ok(flags) is False
    assert json.loads(flags_to_storage(flags)) == flags


def test_dimension_median_not_mean_on_asymmetric_members():
    # Three clean member zs: median 0.2, mean ~33.47
    rows = []
    base = {
        "fiscal_period": "FY2024-Q1",
        "earnings_date": "2023-12-20",
        "earnings_datetime": pd.Timestamp("2023-12-20 16:00:00"),
        "alpha_spec_0_90": 0.01,
        "alpha_spec_0_90_z": 0.5,
        "alpha_spec_0_90_complete": True,
        "period_role": SURPRISE_ROLE,
        "consensus_pre_mean": 10.0,
        "actual_value": 10.5,
        "fwd_estimate_revision_pct": np.nan,
    }
    for measure, surprise_pct in ((6, 0.1), (8, 0.2), (27, 100.0)):
        rows.append(
            {
                **base,
                "measure": measure,
                "earnings_surprise_pct": surprise_pct,
            }
        )
    df = pd.DataFrame(rows)
    # Skip PIT history requirement by injecting already-computed z columns
    df["earnings_surprise_pct_z_pit"] = [0.1, 0.2, 100.0]
    df["earnings_surprise_pct_z"] = [0.1, 0.2, 100.0]
    dims = build_dimension_scores(df)
    row = dims.iloc[0]
    assert row["dim_margins_z"] == pytest.approx(0.2)
    assert row["dim_margins_z_mean_audit"] == pytest.approx((0.1 + 0.2 + 100.0) / 3)
    assert int(row["dim_margins_z_members"]) == 3


def test_apply_consensus_gates_nulls_mu_like_pct():
    df = pd.DataFrame(
        [
            {
                "measure": 27,
                "period_role": SURPRISE_ROLE,
                "actual_value": 37.0,
                "consensus_pre_mean": -0.67957,
                "earnings_surprise_pct": 55.446,
                "fwd_estimate_revision_pct": 0.0,
            }
        ]
    )
    gated = apply_consensus_gates(df)
    assert pd.isna(gated.loc[0, "earnings_surprise_pct"])
    assert bool(gated.loc[0, "near_zero_consensus"]) is True
    assert bool(gated.loc[0, "pct_surprise_usable"]) is False


def test_margins_dimension_spec_includes_gross_margin():
    assert 27 in DIMENSIONS["margins"]["measures"]
