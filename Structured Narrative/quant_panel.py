#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared quant sign-match and panel derivation helpers."""
from __future__ import annotations

import pandas as pd

from dimension_scorer import QUANT_COMPARABLE_DIMENSIONS


def sign(x, eps: float = 1e-9) -> int | None:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if abs(float(x)) < eps:
        return 0
    return 1 if float(x) > 0 else -1


def agrees(a, b) -> bool | None:
    sa, sb = sign(a), sign(b)
    if sa in (None, 0) or sb in (None, 0):
        return None
    return sa == sb


def narrative_quant_gap(surprise_mag, quant_z) -> float | None:
    if quant_z is None or (isinstance(quant_z, float) and pd.isna(quant_z)):
        return None
    if surprise_mag is None or (isinstance(surprise_mag, float) and pd.isna(surprise_mag)):
        return None
    q = max(-2.0, min(2.0, float(quant_z)))
    return round(float(surprise_mag) - q, 2)


def same_sign(a, b) -> bool | None:
    if pd.isna(a) or pd.isna(b):
        return None
    fa, fb = float(a), float(b)
    if fa == 0 and fb == 0:
        return True
    if fa == 0 or fb == 0:
        return None
    return (fa > 0) == (fb > 0)


def apply_derived_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Add derived modeling columns and multi-layer divergence flags."""
    df = panel.copy()
    df["has_quant_z"] = df["quant_z"].notna()

    df["abs_narrative_quant_gap"] = df["narrative_quant_gap"].abs()
    df["surprise_quant_interaction"] = df.apply(
        lambda r: (
            round(float(r["surprise_magnitude"]) * float(r["quant_z"]), 3)
            if pd.notna(r.get("surprise_magnitude")) and pd.notna(r.get("quant_z"))
            else None
        ),
        axis=1,
    )

    df = df.sort_values(["ticker", "dimension", "fiscal_period"]).reset_index(drop=True)
    for col, src in (("llm_level_4q_mean", "llm_level"), ("change_magnitude_4q_mean", "change_magnitude")):
        df[col] = (
            df.groupby(["ticker", "dimension"], dropna=False)[src]
            .transform(lambda s: s.rolling(window=4, min_periods=1).mean())
        )

    comparable = df["dimension"].isin(QUANT_COMPARABLE_DIMENSIONS)

    def _level_match(r):
        if r["dimension"] not in QUANT_COMPARABLE_DIMENSIONS:
            return pd.NA
        return same_sign(r.get("llm_level"), r.get("quant_z"))

    def _delta_match(r):
        if r["dimension"] not in QUANT_COMPARABLE_DIMENSIONS:
            return pd.NA
        return same_sign(r.get("change_magnitude"), r.get("quant_z_delta"))

    df["level_quant_sign_match"] = df.apply(_level_match, axis=1).astype("boolean")
    df["delta_quant_sign_match"] = df.apply(_delta_match, axis=1).astype("boolean")

    df["level_diverges"] = (
        df["level_quant_sign_match"].eq(False).where(comparable, other=pd.NA).astype("boolean")
    )
    df["delta_diverges"] = (
        df["delta_quant_sign_match"].eq(False).where(comparable, other=pd.NA).astype("boolean")
    )
    df["surprise_diverges"] = df["agrees_with_quant"].eq(False).astype("boolean")
    df["any_quant_divergence"] = (
        df["level_diverges"].eq(True)
        | df["delta_diverges"].eq(True)
        | df["surprise_diverges"].eq(True)
    )
    df["is_divergence"] = df["surprise_diverges"]
    return df
