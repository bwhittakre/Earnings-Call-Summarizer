#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build slim cross-sectional spine exports from feature panels."""
from __future__ import annotations

import pandas as pd

from dimension_scorer import NARRATIVE_ONLY_DIMENSIONS, QUANT_COMPARABLE_DIMENSIONS
from quant_mapping import quant_family_for, quant_mapping_for

CONSOLIDATED_SPINE_COLUMNS = [
    "ticker",
    "fiscal_period",
    "period_end_date",
    "period_end_calendar_quarter",
    "earnings_date",
    "feature_availability_date",
    "dimension",
    "dimension_group",
    "quant_mapping",
    "quant_family",
    "llm_level",
    "change_direction",
    "change_magnitude",
    "surprise_magnitude",
    "narrative_novelty",
    "novelty_direction",
    "quant_z_pit",
    "quant_guidance_revision_z_pit",
    "agrees_with_quant",
    "evidence_confidence",
]


def evidence_confidence(row: pd.Series) -> float | None:
    """Minimum evidence supported pct across populated narrative layers."""
    pcts: list[float] = []
    for col in (
        "level_evidence_supported_pct",
        "delta_evidence_supported_pct",
        "surprise_evidence_supported_pct",
        "novelty_evidence_supported_pct",
    ):
        v = row.get(col)
        if pd.notna(v):
            pcts.append(float(v))
    if not pcts:
        return None
    return round(min(pcts), 4)


def panel_to_spine(panel: pd.DataFrame) -> pd.DataFrame:
    """Project a feature panel to the slim cross-sectional schema."""
    df = panel.copy()
    if "quant_z_pit" not in df.columns and "quant_z" in df.columns:
        df["quant_z_pit"] = df["quant_z"]

    df["quant_mapping"] = df["dimension"].map(lambda d: quant_mapping_for(str(d)))
    if "quant_family" not in df.columns:
        df["quant_family"] = df["dimension"].map(quant_family_for)

    df["evidence_confidence"] = df.apply(evidence_confidence, axis=1)

    for col in CONSOLIDATED_SPINE_COLUMNS:
        if col not in df.columns:
            df[col] = None

    return df[CONSOLIDATED_SPINE_COLUMNS].copy()


def validate_spine_rules(spine: pd.DataFrame) -> list[str]:
    """Check surprise vs novelty mutual exclusivity and availability rules."""
    errors: list[str] = []
    quant_dims = set(QUANT_COMPARABLE_DIMENSIONS)
    narrative_dims = set(NARRATIVE_ONLY_DIMENSIONS)

    for _, row in spine.iterrows():
        dim = row["dimension"]
        has_surprise = pd.notna(row.get("surprise_magnitude"))
        has_novelty = pd.notna(row.get("narrative_novelty"))
        if dim in quant_dims and has_novelty:
            errors.append(f"{row['fiscal_period']} {dim}: novelty populated on quant-comparable dim")
        if dim in narrative_dims and has_surprise:
            errors.append(f"{row['fiscal_period']} {dim}: surprise populated on narrative-only dim")
        if dim == "guidance" and pd.notna(row.get("quant_z_pit")):
            errors.append(f"{row['fiscal_period']} guidance: quant_z_pit should be null at call")
        delayed = row.get("quant_guidance_revision_z_pit")
        avail = row.get("feature_availability_date")
        earn = row.get("earnings_date")
        if pd.notna(delayed) and pd.notna(avail) and pd.notna(earn) and dim == "guidance":
            if str(avail) == str(earn):
                errors.append(
                    f"{row['fiscal_period']} guidance: feature_availability_date should be T+7 when revision z present"
                )
    return errors
