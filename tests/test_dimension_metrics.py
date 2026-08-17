"""Membership, sign-flip, and sparse-floor tests for strengthened dimensions."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SN = Path(__file__).resolve().parents[1] / "Structured Narrative"
if str(SN) not in sys.path:
    sys.path.insert(0, str(SN))

from company_config import CORE_MEASURES  # noqa: E402
from narrative_zscore import DIMENSIONS, SURPRISE_ROLE, apply_dimension_signs, build_dimension_scores  # noqa: E402
from quant_mapping import measure_label, quant_mapping_for  # noqa: E402
from quant_quality import FLAG_SPARSE_DIMENSION, SPARSE_DIMENSION_MIN_MEMBERS, dimension_quality_flags  # noqa: E402


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
    spec = DIMENSIONS["guidance"]
    assert spec["family"] == "revision"
    assert spec["measures"] != "all"
    assert isinstance(spec["measures"], list)
    assert len(spec["measures"]) >= 4
    assert "all" not in quant_mapping_for("guidance").lower()


def test_measure_label_sees_core_and_candidates():
    assert measure_label(20) == "Sales"
    assert measure_label(219) == "SG&A"
    assert measure_label(373) == CORE_MEASURES[373]
    assert measure_label(17) == "Pretax Profit"
    assert measure_label(4) == "Dividend Per Share"
    assert "Measure 373" not in measure_label(373)
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
    assert 22 not in signs  # capex keeps raw sign


def test_opex_sign_flip_changes_margins_median():
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
        rows.append({**base, "measure": measure, "earnings_surprise_pct_z_pit": z, "earnings_surprise_pct_z": z})
    dims = build_dimension_scores(pd.DataFrame(rows))
    # Gross-margin +1 and SG&A spend-beat +1 flip to -1 -> median 0.
    assert dims.iloc[0]["dim_margins_z"] == pytest.approx(0.0)


def test_apply_dimension_signs_flips_listed_codes_only():
    spec = {"sign": {219: -1}}
    sub = pd.DataFrame({"measure": [27, 219], "z": [1.0, 1.0]})
    out = apply_dimension_signs(sub, spec, "z")
    assert out["z"].tolist() == [1.0, -1.0]


def test_sparse_dimension_floor_is_three():
    assert SPARSE_DIMENSION_MIN_MEMBERS == 3
    two = dimension_quality_flags(member_zs_clean=[0.1, 0.2, None])
    assert FLAG_SPARSE_DIMENSION in two
    three = dimension_quality_flags(member_zs_clean=[0.1, 0.2, 0.3])
    assert FLAG_SPARSE_DIMENSION not in three
    two_explicit = dimension_quality_flags(member_zs_clean=[0.1, 0.2, None], min_members=2)
    assert FLAG_SPARSE_DIMENSION not in two_explicit
