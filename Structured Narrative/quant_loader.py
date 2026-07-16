#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load point-in-time dimension z-scores from the quant spine."""
from __future__ import annotations

import pandas as pd

from dimension_scorer import QUANT_COMPARABLE_DIMENSIONS
from quant_mapping import CALL_DATE_QUANT_DIMS
from output_paths import resolve_read_parquet_or_csv


def _read_dimension_scores(ticker: str) -> pd.DataFrame | None:
    quant_dim_file = resolve_read_parquet_or_csv(ticker, "dimension_scores", layer="parquet")
    if quant_dim_file is None:
        return None
    return (
        pd.read_parquet(quant_dim_file)
        if quant_dim_file.suffix == ".parquet"
        else pd.read_csv(quant_dim_file)
    )


def load_quant_spine_meta(ticker: str) -> dict[str, dict[str, str | None]]:
    """Return fiscal_period -> {earnings_date, model_date, period_end_date}."""
    df = _read_dimension_scores(ticker)
    if df is None or "fiscal_period" not in df.columns:
        return {}
    out: dict[str, dict[str, str | None]] = {}
    for _, r in df.iterrows():
        fp = str(r["fiscal_period"])
        ped = r.get("fiscal_quarter_end")
        if pd.isna(ped):
            ped = r.get("period_end_date")
        out[fp] = {
            "earnings_date": str(r["earnings_date"]) if pd.notna(r.get("earnings_date")) else None,
            "model_date": str(r["model_date"]) if pd.notna(r.get("model_date")) else None,
            "period_end_date": str(ped)[:10] if pd.notna(ped) else None,
        }
    return out


def load_quant_dim_z(ticker: str) -> dict[str, dict[str, float | None]]:
    """Return fiscal_period -> dimension -> call-date PIT quant z (alias for load_quant_z_pit)."""
    return load_quant_z_pit(ticker)


def load_quant_z_pit(ticker: str) -> dict[str, dict[str, float | None]]:
    """Call-date PIT z for surprise-family dims; guidance is null at call."""
    df = _read_dimension_scores(ticker)
    if df is None or "fiscal_period" not in df.columns:
        return {}
    out: dict[str, dict[str, float | None]] = {}
    for _, r in df.iterrows():
        fp = str(r["fiscal_period"])
        vals: dict[str, float | None] = {}
        for dim in QUANT_COMPARABLE_DIMENSIONS:
            if dim == "guidance":
                vals[dim] = None
                continue
            col = f"dim_{dim}_z"
            if col in df.columns and pd.notna(r[col]):
                vals[dim] = round(float(r[col]), 3)
            else:
                vals[dim] = None
        out[fp] = vals
    return out


def load_quant_z_fullsample(ticker: str) -> dict[str, dict[str, float | None]]:
    """Full-sample z for research comparison (not for backtest features)."""
    df = _read_dimension_scores(ticker)
    if df is None or "fiscal_period" not in df.columns:
        return {}
    out: dict[str, dict[str, float | None]] = {}
    for _, r in df.iterrows():
        fp = str(r["fiscal_period"])
        vals: dict[str, float | None] = {}
        for dim in CALL_DATE_QUANT_DIMS:
            col = f"dim_{dim}_z_fullsample"
            if col in df.columns and pd.notna(r[col]):
                vals[dim] = round(float(r[col]), 3)
            else:
                vals[dim] = None
        out[fp] = vals
    return out


def load_quant_guidance_revision_z_pit(ticker: str) -> dict[str, float | None]:
    """T+7d PIT forward-estimate revision z for guidance (delayed feature)."""
    df = _read_dimension_scores(ticker)
    if df is None or "fiscal_period" not in df.columns:
        return {}
    col = "dim_guidance_revision_z_pit"
    if col not in df.columns:
        return {}
    out: dict[str, float | None] = {}
    for _, r in df.iterrows():
        fp = str(r["fiscal_period"])
        if pd.notna(r[col]):
            out[fp] = round(float(r[col]), 3)
        else:
            out[fp] = None
    return out


def quant_z_for(ticker: str, fiscal_period: str, dimension: str) -> float | None:
    return load_quant_z_pit(ticker).get(fiscal_period, {}).get(dimension)
