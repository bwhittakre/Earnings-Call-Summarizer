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
        "description": (
            "Available at or immediately after the earnings call. "
            "Availability stamped in call_feature_available_date "
            "(feature_availability_date is the same for display/compat)."
        ),
        "columns": [
            "as_of_date",
            "call_feature_available_date",
            "feature_availability_date",
            "llm_level",
            "change_magnitude",
            "surprise_magnitude",
            "narrative_novelty",
            "quant_z_pit",
        ],
    },
    "t_plus_7": {
        "description": (
            "Available after the T+7 estimate revision window (model_date). "
            "Availability stamped in t7_feature_available_date. "
            "Pair only with forward-return labels that start on or after this date "
            "(alpha_spec_* uses t+7 entry)."
        ),
        "columns": [
            "t7_feature_available_date",
            "quant_guidance_revision_z_pit",
        ],
    },
    "label_only_event": {
        "description": (
            "Event-driven forward return labels — not model inputs. "
            "Compounded from each company's model_date (T+7 entry)."
        ),
        "columns": [
            "alpha_spec_0_90",
            "alpha_spec_0_90_z",
            "alpha_spec_0_90_complete",
        ],
    },
    "label_only_asof": {
        "description": (
            "Cross-sectional forward return labels — not model inputs. "
            "Compounded from investable_as_of_date (common as-of in the calendar-quarter bucket)."
        ),
        "columns": [
            "alpha_spec_asof_0_90",
            "alpha_spec_asof_0_90_z",
            "alpha_spec_asof_0_90_complete",
        ],
    },
    # Compat alias used by older readers
    "label_only": {
        "description": (
            "Forward return labels — not model inputs. "
            "Prefer label_only_event / label_only_asof for explicit entry dates."
        ),
        "columns": [
            "alpha_spec_0_90",
            "alpha_spec_0_90_z",
            "alpha_spec_0_90_complete",
            "alpha_spec_asof_0_90",
            "alpha_spec_asof_0_90_z",
            "alpha_spec_asof_0_90_complete",
        ],
    },
}
