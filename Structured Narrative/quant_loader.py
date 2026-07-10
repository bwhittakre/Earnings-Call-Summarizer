#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load point-in-time dimension z-scores from the quant spine."""
from __future__ import annotations

import pandas as pd

from dimension_scorer import QUANT_COMPARABLE_DIMENSIONS
from output_paths import resolve_read_parquet_or_csv


def load_quant_dim_z(ticker: str) -> dict[str, dict[str, float | None]]:
    """Return fiscal_period -> dimension -> PIT quant z (dim_*_z in dimension_scores)."""
    quant_dim_file = resolve_read_parquet_or_csv(ticker, "dimension_scores", layer="parquet")
    if quant_dim_file is None:
        return {}
    df = (
        pd.read_parquet(quant_dim_file)
        if quant_dim_file.suffix == ".parquet"
        else pd.read_csv(quant_dim_file)
    )
    if "fiscal_period" not in df.columns:
        return {}
    out: dict[str, dict[str, float | None]] = {}
    for _, r in df.iterrows():
        fp = str(r["fiscal_period"])
        vals: dict[str, float | None] = {}
        for dim in QUANT_COMPARABLE_DIMENSIONS:
            col = f"dim_{dim}_z"
            if col in df.columns and pd.notna(r[col]):
                vals[dim] = round(float(r[col]), 3)
            else:
                vals[dim] = None
        out[fp] = vals
    return out


def quant_z_for(ticker: str, fiscal_period: str, dimension: str) -> float | None:
    return load_quant_dim_z(ticker).get(fiscal_period, {}).get(dimension)
