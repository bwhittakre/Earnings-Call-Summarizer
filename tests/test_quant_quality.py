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


QUANT_DIMS = (
    "demand",
    "margins",
    "earnings_power",
    "capital_allocation",
    "guidance",
)


def _codes(spec: dict) -> list[int]:
    measures = spec["measures"]
    assert measures != "all"
    return [int(c) for c in measures]


def test_each_quant_dim_has_at_least_three_mapped_codes():
    for dim in QUANT_DIMS:
        assert len(_codes(DIMENSIONS[dim])) >= 3, dim


def test_dims_with_fourth_member_have_at_least_four():
    for dim in ("demand", "margins", "earnings_power", "capital_allocation", "guidance"):
        assert len(_codes(DIMENSIONS[dim])) >= 4, dim


def test_no_surprise_measure_reused_across_dimensions():
    seen: dict[int, str] = {}
    for dim, spec in DIMENSIONS.items():
        if spec["family"] != "surprise":
            continue
        for code in _codes(spec):
            assert code not in seen, f"{code} in {seen.get(code)} and {dim}"
            seen[code] = dim


def test_guidance_is_curated_list_not_all():
    from quant_mapping import quant_mapping_for

    spec = DIMENSIONS["guidance"]
    assert spec["family"] == "revision"
    assert spec["measures"] != "all"
    assert isinstance(spec["measures"], list)
    assert len(spec["measures"]) >= 4
    assert "all measures" not in quant_mapping_for("guidance").lower()


def test_measure_label_sees_core_and_candidates():
    from company_config import CORE_MEASURES
    from quant_mapping import measure_label

    assert measure_label(20) == "Sales"
    assert measure_label(219) == "SG&A"
    assert measure_label(373) == CORE_MEASURES[373]
    assert measure_label(17) == "Pretax Profit"
    assert measure_label(4) == "Dividend Per Share"
    assert not measure_label(373).startswith("Measure ")
    for code in CORE_MEASURES:
        assert not measure_label(code).startswith("Measure ")


def test_opex_in_margins_has_explicit_negative_sign():
    signs = DIMENSIONS["margins"].get("sign") or {}
    assert signs.get(219) == -1
    assert signs.get(185) == -1
    assert 219 in DIMENSIONS["margins"]["measures"]
    assert 185 in DIMENSIONS["margins"]["measures"]


def test_net_debt_in_capital_allocation_has_explicit_negative_sign():
    signs = DIMENSIONS["capital_allocation"].get("sign") or {}
    assert signs.get(14) == -1
    assert 14 in DIMENSIONS["capital_allocation"]["measures"]
    assert 22 not in signs


def test_opex_sign_flip_changes_margins_median():
    from narrative_zscore import apply_dimension_signs

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
        "earnings_surprise_pct": 0.1,
    }
    rows = []
    for measure, z in ((27, 1.0), (219, 1.0)):
        rows.append(
            {
                **base,
                "measure": measure,
                "earnings_surprise_pct_z_pit": z,
                "earnings_surprise_pct_z": z,
            }
        )
    dims = build_dimension_scores(pd.DataFrame(rows))
    assert dims.iloc[0]["dim_margins_z"] == pytest.approx(0.0)

    spec = {"sign": {219: -1}}
    sub = pd.DataFrame({"measure": [27, 219], "z": [1.0, 1.0]})
    out = apply_dimension_signs(sub, spec, "z")
    assert out["z"].tolist() == [1.0, -1.0]


def test_sparse_dimension_floor_is_three():
    from quant_quality import SPARSE_DIMENSION_MIN_MEMBERS

    assert SPARSE_DIMENSION_MIN_MEMBERS == 3
    two = dimension_quality_flags(member_zs_clean=[0.1, 0.2, None])
    assert FLAG_SPARSE_DIMENSION in two
    three = dimension_quality_flags(member_zs_clean=[0.1, 0.2, 0.3])
    assert FLAG_SPARSE_DIMENSION not in three
    two_explicit = dimension_quality_flags(
        member_zs_clean=[0.1, 0.2, None], min_members=2
    )
    assert FLAG_SPARSE_DIMENSION not in two_explicit
