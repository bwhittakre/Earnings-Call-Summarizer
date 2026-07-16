#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AMZN Narrative-Quant Z-Score / Dimension-Score Analysis Layer
=============================================================

Read-only layer on top of the extractor output
(``output/AMZN_narrative_quant.parquet``). It makes the raw point-in-time
signals *comparative* by standardizing them against AMZN's own history, and
rolls the standardized measures into a per-quarter "dimension score" vector.

Why z-scores
------------
AMZN structurally beats consensus on some measures nearly every quarter, so a
raw "+4% EPS beat" is meaningless without knowing AMZN's own distribution.
Standardizing each measure against AMZN's history answers the shareable
question: *how unusual was this quarter, in standard deviations, versus how
AMZN normally prints?*  0 == AMZN-typical, +1.5 == unusually strong, etc.

Z-score method (point-in-time only for published outputs):

  * Measure-level ``*_z_pit`` is computed with an expanding window using events
    STRICTLY BEFORE t (``MIN_HISTORY`` prior observations required).
  * ``dim_*_z`` in ``dimension_scores`` uses these PIT values only — safe for
    backtest and live-quarter inference.
  * Full-sample ``*_z`` is still computed in the long enriched table for ad-hoc
    descriptive analysis but is NOT written to ``dimension_scores``.

Grouping is per ``(measure, period_role)``:
  * surprise family  -> ``earnings_surprise_pct``      on ``reported_q`` rows
  * revision family  -> ``fwd_estimate_revision_pct``  on next_q / fy1 / fy2 rows

Dimension scores (bridge to the future LLM dimension score)
----------------------------------------------------------
Surviving measures are mapped to fixed business dimensions. A dimension's
z-score for an event is the mean of its member measure z-scores. The output is
one vector per fiscal quarter -- deliberately the same shape the LLM narrative
dimension scores will later occupy, so Focus 1 slots in beside it.

Sign convention: kept RAW (e.g. a capex "beat" = higher capex stays positive;
higher stock-based comp stays positive). Dimension-level sign interpretation is
a labeling step deferred to the LLM dimension slice.

Outputs (output/):
  * AMZN_narrative_zscored.parquet / .csv   (enriched long table)
  * AMZN_dimension_scores.parquet  / .csv   (wide, one row per quarter)

Usage:
  python narrative_zscore.py            # standard mean/std z
  python narrative_zscore.py --robust   # median/MAD (fat-tail-resistant) z
"""

import os
import sys
import argparse

import numpy as np
import pandas as pd

from output_paths import company_artifact, resolve_read_parquet_or_csv

HERE = os.path.dirname(os.path.abspath(__file__))

MIN_HISTORY = 8  # prior observations required before a PIT z is defined

SURPRISE_ROLE = "reported_q"
REVISION_ROLES = ("next_q", "fy1", "fy2")

# Forward roles that best proxy management guidance / how the call was received.
GUIDANCE_ROLES = ("next_q", "fy1")

# Fixed business dimensions. Membership is by LSEG measure code; only measures
# actually present (i.e. that cleared the extractor's coverage gate) are used.
#   demand              20 Sales, 431 GMV, 418 Advertising Rev, 373 Deferred Rev
#   margins             6 EBIT, 8 EBITDA, 27 Gross Margin
#   earnings_power      9 EPS
#   capital_allocation  237 Free Cash Flow, 22 Capex, 213 Stock-Based Comp
#   guidance            forward revision family across all measures
DIMENSIONS = {
    "demand":             {"measures": [20, 431, 418, 373], "family": "surprise"},
    "margins":            {"measures": [6, 8, 27],           "family": "surprise"},
    "earnings_power":     {"measures": [9],                  "family": "surprise"},
    "capital_allocation": {"measures": [237, 22, 213],       "family": "surprise"},
    "guidance":           {"measures": "all",                "family": "revision"},
}


# ── Z-score primitives ────────────────────────────────────────────────────────
def _full_sample_z(x: pd.Series, robust: bool) -> pd.Series:
    """Standardize the whole series. Population std (ddof=0) so std(z)==1 exactly.
    Robust variant uses median / (1.4826 * MAD)."""
    v = x.astype(float)
    if robust:
        med = v.median()
        mad = (v - med).abs().median()
        scale = 1.4826 * mad
        return (v - med) / scale if scale and not np.isnan(scale) else v * np.nan
    mu = v.mean()
    sd = v.std(ddof=0)
    return (v - mu) / sd if sd and not np.isnan(sd) else v * np.nan


def _pit_z(g: pd.DataFrame, val: str, robust: bool) -> pd.Series:
    """Expanding, strictly-prior z within an already-time-sorted group.
    mean/std (or median/MAD) use only events before the current one and require
    at least MIN_HISTORY prior observations; otherwise NaN."""
    x = g[val].astype(float)
    prior = x.shift(1)  # exclude the current event -> strictly point-in-time
    if robust:
        med = prior.expanding(min_periods=MIN_HISTORY).median()
        # rolling MAD via expanding apply on the shifted series
        mad = prior.expanding(min_periods=MIN_HISTORY).apply(
            lambda a: np.nanmedian(np.abs(a - np.nanmedian(a))), raw=True)
        scale = 1.4826 * mad
        return (x - med) / scale.replace(0.0, np.nan)
    mu = prior.expanding(min_periods=MIN_HISTORY).mean()
    sd = prior.expanding(min_periods=MIN_HISTORY).std(ddof=0)
    return (x - mu) / sd.replace(0.0, np.nan)


def add_group_z(df: pd.DataFrame, roles, val: str, prefix: str, robust: bool):
    """Add ``{prefix}_z`` and ``{prefix}_z_pit`` for rows whose period_role is in
    ``roles``, grouped by (measure, period_role), ordered by earnings_datetime."""
    z_col, zpit_col = f"{prefix}_z", f"{prefix}_z_pit"
    df[z_col] = np.nan
    df[zpit_col] = np.nan

    mask = df["period_role"].isin(roles) & df[val].notna()
    work = df[mask].copy()
    if work.empty:
        return df

    # Full-sample z per (measure, role).
    df.loc[mask, z_col] = (
        work.groupby(["measure", "period_role"])[val]
            .transform(lambda s: _full_sample_z(s, robust))
    )

    # PIT expanding z per (measure, role), time-ordered.
    zpit = {}
    for _, g in work.groupby(["measure", "period_role"]):
        g = g.sort_values("earnings_datetime")
        zpit.update(_pit_z(g, val, robust).to_dict())
    df.loc[list(zpit.keys()), zpit_col] = pd.Series(zpit)
    return df


# ── Build ───────────────────────────────────────────────────────────────────
def build_enriched(df: pd.DataFrame, robust: bool) -> pd.DataFrame:
    df = df.copy()
    df["earnings_datetime"] = pd.to_datetime(df["earnings_datetime"])

    df = add_group_z(df, [SURPRISE_ROLE], "earnings_surprise_pct",
                     "earnings_surprise_pct", robust)
    df = add_group_z(df, list(REVISION_ROLES), "fwd_estimate_revision_pct",
                     "fwd_estimate_revision_pct", robust)

    # Event-level forward-return (alpha) z, broadcast back to every row.
    ev = (df.dropna(subset=["alpha_spec_0_90"])
            .groupby("fiscal_period")
            .agg(alpha_spec_0_90=("alpha_spec_0_90", "first"))
            .reset_index())
    if not ev.empty:
        ev["alpha_spec_0_90_z"] = _full_sample_z(ev["alpha_spec_0_90"], robust)
        df = df.merge(ev[["fiscal_period", "alpha_spec_0_90_z"]],
                      on="fiscal_period", how="left")
    else:
        df["alpha_spec_0_90_z"] = np.nan
    return df


def build_dimension_scores(df: pd.DataFrame) -> pd.DataFrame:
    """One row per fiscal quarter: dimension z vectors (full-sample + PIT) plus
    the forward-return label for context."""
    # Event spine, time-ordered.
    agg_cols = {
        "earnings_date": ("earnings_date", "first"),
        "earnings_datetime": ("earnings_datetime", "first"),
        "alpha_spec_0_90": ("alpha_spec_0_90", "first"),
        "alpha_spec_0_90_z": ("alpha_spec_0_90_z", "first"),
        "alpha_spec_0_90_complete": ("alpha_spec_0_90_complete", "first"),
    }
    if "model_date" in df.columns:
        agg_cols["model_date"] = ("model_date", "first")
    if "fiscal_quarter_end" in df.columns:
        agg_cols["fiscal_quarter_end"] = ("fiscal_quarter_end", "first")
    spine = (
        df.groupby("fiscal_period")
        .agg(**agg_cols)
        .reset_index()
        .sort_values("earnings_datetime")
        .reset_index(drop=True)
    )

    present = set(df["measure"].unique())

    def dim_series(spec, zsuffix):
        """Mean of member measure z-scores per event for one dimension."""
        fam = spec["family"]
        if fam == "surprise":
            col = f"earnings_surprise_pct_{zsuffix}"
            sub = df[df["period_role"] == SURPRISE_ROLE]
        else:  # revision -> guidance
            col = f"fwd_estimate_revision_pct_{zsuffix}"
            sub = df[df["period_role"].isin(GUIDANCE_ROLES)]

        if spec["measures"] != "all":
            members = [m for m in spec["measures"] if m in present]
            sub = sub[sub["measure"].isin(members)]

        return (sub.dropna(subset=[col])
                   .groupby("fiscal_period")[col].mean())

    for dim, spec in DIMENSIONS.items():
        pit = dim_series(spec, "z_pit")
        full = dim_series(spec, "z")
        if dim == "guidance":
            # Call-date quant for guidance is null; revision z is T+7d delayed feature.
            spine["dim_guidance_z"] = np.nan
            spine["dim_guidance_revision_z_pit"] = spine["fiscal_period"].map(pit)
        else:
            spine[f"dim_{dim}_z"] = spine["fiscal_period"].map(pit)
            spine[f"dim_{dim}_z_fullsample"] = spine["fiscal_period"].map(full)

    return spine


def write_parquet(df: pd.DataFrame, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_parquet(path, index=False)
    print(f"Wrote {path}  ({len(df)} rows)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="AMZN", help="Ticker symbol.")
    ap.add_argument("--robust", action="store_true",
                    help="use median/MAD z instead of mean/std")
    args = ap.parse_args()
    ticker = args.ticker.upper()

    in_path = resolve_read_parquet_or_csv(ticker, "narrative_quant", layer="parquet")
    if in_path is None:
        sys.exit(
            f"Input not found for {ticker}. "
            f"Run single_company_extractor.py --ticker {ticker} first."
        )
    out_long_parquet = str(company_artifact(ticker, "parquet", "narrative_zscored", "parquet", mkdir=True))
    out_dim_parquet = str(company_artifact(ticker, "parquet", "dimension_scores", "parquet", mkdir=True))

    raw = pd.read_parquet(in_path) if in_path.suffix == ".parquet" else pd.read_csv(in_path)
    print(f"Loaded {in_path}  ({len(raw)} rows, "
          f"{raw['fiscal_period'].nunique()} quarters)")
    print(f"Z method: {'robust median/MAD' if args.robust else 'mean/std'}  "
          f"(MIN_HISTORY={MIN_HISTORY} for PIT)\n")

    enriched = build_enriched(raw, args.robust)
    dims = build_dimension_scores(enriched)

    write_parquet(enriched, out_long_parquet)
    write_parquet(dims, out_dim_parquet)
    return enriched, dims


if __name__ == "__main__":
    main()
