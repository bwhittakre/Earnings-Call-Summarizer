#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Human-readable quantitative measure mapping per narrative dimension."""
from __future__ import annotations

from company_config import CORE_MEASURES
from narrative_zscore import DIMENSIONS

_MEASURE_NAMES = dict(CORE_MEASURES)


def measure_label(code: int) -> str:
    return _MEASURE_NAMES.get(code, f"Measure {code}")


def quant_mapping_for(dimension: str, *, ticker: str | None = None) -> str:
    """Return comma-separated LSEG measure names for a dimension."""
    spec = DIMENSIONS.get(dimension)
    if spec is None:
        return ""
    if spec["measures"] == "all":
        return "Forward estimate revisions (all measures)"
    codes = spec["measures"]
    return ", ".join(measure_label(int(c)) for c in codes)


def quant_family_for(dimension: str) -> str | None:
    spec = DIMENSIONS.get(dimension)
    if spec is None:
        return None
    return str(spec["family"])


# Dimensions with call-date PIT surprise z (excludes guidance — T+7d revision).
CALL_DATE_QUANT_DIMS = (
    "demand",
    "margins",
    "earnings_power",
    "capital_allocation",
)

FEATURE_AVAILABILITY_MANIFEST = {
    "call_date": {
        "description": "Available at or immediately after the earnings call.",
        "columns": [
            "as_of_date",
            "feature_availability_date",
            "llm_level",
            "change_magnitude",
            "surprise_magnitude",
            "narrative_novelty",
            "quant_z_pit",
        ],
    },
    "t_plus_7": {
        "description": "Available after the 7-business-day estimate revision window.",
        "columns": [
            "quant_guidance_revision_z_pit",
        ],
    },
    "label_only": {
        "description": "Forward return labels — not model inputs.",
        "columns": [
            "alpha_spec_0_90",
            "alpha_spec_0_90_z",
            "alpha_spec_0_90_complete",
        ],
    },
}
