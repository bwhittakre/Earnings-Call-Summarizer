#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thematic dimension display order for consolidated panel outputs."""
from __future__ import annotations

import pandas as pd

from dimension_scorer import ALL_DIMENSIONS

DEFAULT_PRESET = "fundamentals_context"

DIMENSION_GROUP_LABELS = {
    "fundamentals": "Fundamentals",
    "narrative_context": "Narrative context",
    "operating_financial": "Operating & financial",
    "behavioral": "Behavioral",
    "industry_external": "Industry / external",
}

ORDER_PRESETS: dict[str, tuple[str, ...]] = {
    "pipeline": ALL_DIMENSIONS,
    "fundamentals_context": (
        "demand",
        "margins",
        "earnings_power",
        "capital_allocation",
        "guidance",
        "management_confidence",
        "competitive_position",
        "macro_regulatory_risk",
    ),
    "behavioral": (
        "demand",
        "margins",
        "earnings_power",
        "capital_allocation",
        "guidance",
        "management_confidence",
        "competitive_position",
        "macro_regulatory_risk",
    ),
    "research_note": (
        "demand",
        "competitive_position",
        "margins",
        "earnings_power",
        "capital_allocation",
        "guidance",
        "management_confidence",
        "macro_regulatory_risk",
    ),
    "risk_first": (
        "macro_regulatory_risk",
        "competitive_position",
        "management_confidence",
        "demand",
        "margins",
        "earnings_power",
        "capital_allocation",
        "guidance",
    ),
}

GROUP_PRESETS: dict[str, dict[str, tuple[str, ...]]] = {
    "pipeline": {
        "fundamentals": (
            "demand",
            "margins",
            "earnings_power",
            "capital_allocation",
            "guidance",
        ),
        "narrative_context": (
            "management_confidence",
            "competitive_position",
            "macro_regulatory_risk",
        ),
    },
    "fundamentals_context": {
        "fundamentals": (
            "demand",
            "margins",
            "earnings_power",
            "capital_allocation",
            "guidance",
        ),
        "narrative_context": (
            "management_confidence",
            "competitive_position",
            "macro_regulatory_risk",
        ),
    },
    "behavioral": {
        "operating_financial": (
            "demand",
            "margins",
            "earnings_power",
            "capital_allocation",
            "guidance",
        ),
        "behavioral": ("management_confidence",),
        "industry_external": (
            "competitive_position",
            "macro_regulatory_risk",
        ),
    },
    "research_note": {
        "fundamentals": (
            "demand",
            "competitive_position",
            "margins",
            "earnings_power",
            "capital_allocation",
            "guidance",
        ),
        "narrative_context": (
            "management_confidence",
            "macro_regulatory_risk",
        ),
    },
    "risk_first": {
        "industry_external": (
            "macro_regulatory_risk",
            "competitive_position",
        ),
        "behavioral": ("management_confidence",),
        "fundamentals": (
            "demand",
            "margins",
            "earnings_power",
            "capital_allocation",
            "guidance",
        ),
    },
}


def resolve_preset(name: str | None) -> str:
    key = (name or DEFAULT_PRESET).strip().lower()
    if key not in ORDER_PRESETS:
        known = ", ".join(sorted(ORDER_PRESETS))
        raise ValueError(f"Unknown dimension-order preset {name!r}. Choose from: {known}")
    return key


def dimension_display_order(preset: str | None = None) -> tuple[str, ...]:
    return ORDER_PRESETS[resolve_preset(preset)]


def dimension_groups(preset: str | None = None) -> dict[str, tuple[str, ...]]:
    return GROUP_PRESETS[resolve_preset(preset)]


def dimension_sort_key(dimension: str, preset: str | None = None) -> int:
    order = dimension_display_order(preset)
    rank = {d: i for i, d in enumerate(order)}
    return rank.get(str(dimension), len(order))


def dimension_group(dimension: str, preset: str | None = None) -> str | None:
    for group, dims in dimension_groups(preset).items():
        if str(dimension) in dims:
            return group
    return None


def dimension_group_label(group: str | None) -> str:
    if not group:
        return ""
    return DIMENSION_GROUP_LABELS.get(group, group.replace("_", " ").title())


def apply_dimension_group_column(
    df: pd.DataFrame,
    preset: str | None = None,
) -> pd.DataFrame:
    """Add dimension_group column from preset mapping."""
    out = df.copy()
    mapping = {
        dim: group
        for group, dims in dimension_groups(preset).items()
        for dim in dims
    }
    out["dimension_group"] = out["dimension"].astype(str).map(mapping)
    return out


def sort_panel_by_dimension(
    df: pd.DataFrame,
    preset: str | None = None,
    *,
    leading_columns: tuple[str, ...] = (
        "period_end_date",
        "ticker",
        "fiscal_period",
    ),
) -> pd.DataFrame:
    """Sort panel rows by leading columns then thematic dimension order."""
    if df.empty or "dimension" not in df.columns:
        return df.reset_index(drop=True)

    out = df.copy()
    preset_key = resolve_preset(preset)
    out["_dim_sort"] = out["dimension"].map(lambda d: dimension_sort_key(d, preset_key))
    sort_cols = [c for c in leading_columns if c in out.columns]
    sort_cols.append("_dim_sort")
    out = out.sort_values(sort_cols).drop(columns=["_dim_sort"]).reset_index(drop=True)
    return out


def prepare_consolidated_panel(
    df: pd.DataFrame,
    preset: str | None = None,
) -> pd.DataFrame:
    """Apply dimension_group column and thematic sort for consolidated exports."""
    out = apply_dimension_group_column(df, preset)
    return sort_panel_by_dimension(out, preset)


def _panel_block_columns(df: pd.DataFrame) -> tuple[str, ...]:
    return tuple(c for c in ("period_end_date", "ticker", "fiscal_period") if c in df.columns)


def insert_dimension_group_header_rows(
    df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[int]]:
    """Insert a labeled row above each dimension_group block within a ticker×quarter block.

    Returns the expanded frame and 0-based row indices of the inserted header rows.
    """
    if df.empty or "dimension_group" not in df.columns:
        return df.reset_index(drop=True), []

    block_cols = _panel_block_columns(df)
    rows: list[dict] = []
    header_indices: list[int] = []
    current_group: str | None = None
    block_key: tuple | None = None

    for _, row in df.iterrows():
        if block_cols:
            key = tuple(row.get(c) for c in block_cols)
            if key != block_key:
                block_key = key
                current_group = None

        grp = row.get("dimension_group")
        grp_key = None if pd.isna(grp) else str(grp)
        if grp_key and grp_key != current_group:
            header = {col: None for col in df.columns}
            header["dimension_group"] = grp_key
            header["dimension"] = dimension_group_label(grp_key)
            header_indices.append(len(rows))
            rows.append(header)
            current_group = grp_key

        rows.append(row.to_dict())

    return pd.DataFrame(rows).reset_index(drop=True), header_indices
