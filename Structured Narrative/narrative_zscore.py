#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AMZN Narrative-Quant Z-Score / Dimension-Score Analysis Layer
=============================================================

Read-only layer on top of the extractor output
(``output/AMZN_narrative_quant.parquet``). It makes the raw point-in-time
signals *comparative* by standardizing them against AMZN's own history, and
rolls the standardized measures into a per-quarter "dimension score" vector
(median of member measure zs; mean retained as audit).

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
decision z-score for an event is the median of its member measure z-scores
(mean retained as ``dim_*_z_mean_audit``). The output is one vector per fiscal
quarter -- deliberately the same shape the LLM narrative dimension scores will
later occupy, so Focus 1 slots in beside it.

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

import argparse
import os
import sys

import numpy as np
import pandas as pd

from output_paths import company_artifact, resolve_read_parquet_or_csv
from quant_quality import (
    consensus_usable,
    dimension_quality_flags,
    flags_from_storage,
    flags_to_storage,
    quality_ok,
)

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


def apply_consensus_gates(df: pd.DataFrame) -> pd.DataFrame:
    """Null percent surprise/revision when consensus is not a usable base.

    Re-applies the extractor gate so historical narrative_quant tables can be
    cleaned without a Snowflake re-pull. Preserves native-unit surprise/revision
    and keeps ungated percent copies for audit z-scores.
    """
    out = df.copy()
    if "earnings_surprise_pct" in out.columns:
        out["earnings_surprise_pct_ungated"] = out["earnings_surprise_pct"]
    if "fwd_estimate_revision_pct" in out.columns:
        out["fwd_estimate_revision_pct_ungated"] = out["fwd_estimate_revision_pct"]
    if "consensus_pre_mean" not in out.columns:
        out["pct_surprise_usable"] = True
        out["near_zero_consensus"] = False
        return out

    usable = []
    near_zero = []
    for _, row in out.iterrows():
        ok = consensus_usable(
            row.get("consensus_pre_mean"),
            row.get("actual_value"),
            row.get("measure"),
        )
        consensus = row.get("consensus_pre_mean")
        has_consensus = pd.notna(consensus)
        usable.append(bool(ok))
        near_zero.append(bool(has_consensus and not ok))
    out["pct_surprise_usable"] = usable
    out["near_zero_consensus"] = near_zero
    blocked = ~out["pct_surprise_usable"]
    if "earnings_surprise_pct" in out.columns:
        out.loc[blocked, "earnings_surprise_pct"] = np.nan
    if "fwd_estimate_revision_pct" in out.columns:
        out.loc[blocked, "fwd_estimate_revision_pct"] = np.nan
    return out


# ── Build ───────────────────────────────────────────────────────────────────
def build_enriched(df: pd.DataFrame, robust: bool) -> pd.DataFrame:
    df = apply_consensus_gates(df)
    df["earnings_datetime"] = pd.to_datetime(df["earnings_datetime"])

    df = add_group_z(df, [SURPRISE_ROLE], "earnings_surprise_pct",
                     "earnings_surprise_pct", robust)
    df = add_group_z(df, list(REVISION_ROLES), "fwd_estimate_revision_pct",
                     "fwd_estimate_revision_pct", robust)
    # Ungated audit zs (same PIT method on pre-gate percent surprises).
    if "earnings_surprise_pct_ungated" in df.columns:
        df = add_group_z(
            df,
            [SURPRISE_ROLE],
            "earnings_surprise_pct_ungated",
            "earnings_surprise_pct_ungated",
            robust,
        )
    if "fwd_estimate_revision_pct_ungated" in df.columns:
        df = add_group_z(
            df,
            list(REVISION_ROLES),
            "fwd_estimate_revision_pct_ungated",
            "fwd_estimate_revision_pct_ungated",
            robust,
        )

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

    def _member_frame(spec, zsuffix, *, ungated: bool = False):
        fam = spec["family"]
        if fam == "surprise":
            prefix = (
                "earnings_surprise_pct_ungated"
                if ungated
                else "earnings_surprise_pct"
            )
            col = f"{prefix}_{zsuffix}"
            sub = df[df["period_role"] == SURPRISE_ROLE].copy()
        else:  # revision -> guidance
            prefix = (
                "fwd_estimate_revision_pct_ungated"
                if ungated
                else "fwd_estimate_revision_pct"
            )
            col = f"{prefix}_{zsuffix}"
            sub = df[df["period_role"].isin(GUIDANCE_ROLES)].copy()

        if spec["measures"] != "all":
            members = [m for m in spec["measures"] if m in present]
            sub = sub[sub["measure"].isin(members)]
        return sub, col

    def dim_series(spec, zsuffix, *, how: str, ungated: bool = False):
        """Aggregate member measure z-scores per event (median decision / mean audit)."""
        sub, col = _member_frame(spec, zsuffix, ungated=ungated)
        if col not in sub.columns or sub.empty:
            return pd.Series(dtype=float)
        grouped = sub.dropna(subset=[col]).groupby("fiscal_period")[col]
        if how == "median":
            return grouped.median()
        if how == "mean":
            return grouped.mean()
        if how == "count":
            return grouped.count()
        raise ValueError(f"Unknown aggregation {how!r}")

    def dim_flags(spec) -> pd.Series:
        """Per-fiscal-period quality flags for one surprise-family dimension."""
        if spec["family"] != "surprise":
            return pd.Series(dtype=object)
        sub, col = _member_frame(spec, "z_pit")
        if sub.empty or col not in sub.columns:
            return pd.Series(dtype=object)
        flag_rows: dict[str, str] = {}
        for fp, g in sub.groupby("fiscal_period"):
            member_zs = {
                int(m): (float(z) if pd.notna(z) else None)
                for m, z in zip(g["measure"], g[col], strict=False)
            }
            # Prefer measure-level near_zero marks; fall back to missing z with
            # non-usable consensus when the long table carries gate columns.
            if "near_zero_consensus" in g.columns:
                near_zero = {
                    int(m): bool(flag)
                    for m, flag in zip(g["measure"], g["near_zero_consensus"], strict=False)
                }
            else:
                near_zero = {
                    int(m): False
                    for m in g["measure"]
                }
            flags = dimension_quality_flags(
                member_zs_clean=member_zs,
                member_near_zero=near_zero,
            )
            flag_rows[str(fp)] = flags_to_storage(flags)
        return pd.Series(flag_rows)

    for dim, spec in DIMENSIONS.items():
        pit = dim_series(spec, "z_pit", how="median")
        full = dim_series(spec, "z", how="median")
        # Audit mean uses ungated member zs so explosive denominators remain visible.
        pit_mean = dim_series(spec, "z_pit", how="mean", ungated=True)
        if pit_mean.empty:
            pit_mean = dim_series(spec, "z_pit", how="mean", ungated=False)
        members = dim_series(spec, "z_pit", how="count")
        if dim == "guidance":
            # Call-date quant for guidance is null; revision z is T+7d delayed feature.
            spine["dim_guidance_z"] = np.nan
            spine["dim_guidance_revision_z_pit"] = spine["fiscal_period"].map(pit)
            spine["dim_guidance_z_mean_audit"] = np.nan
            spine["dim_guidance_z_members"] = spine["fiscal_period"].map(members)
            spine["dim_guidance_quality_flags"] = "[]"
            spine["dim_guidance_quality_ok"] = True
        else:
            spine[f"dim_{dim}_z"] = spine["fiscal_period"].map(pit)
            spine[f"dim_{dim}_z_fullsample"] = spine["fiscal_period"].map(full)
            spine[f"dim_{dim}_z_mean_audit"] = spine["fiscal_period"].map(pit_mean)
            spine[f"dim_{dim}_z_members"] = spine["fiscal_period"].map(members)
            flags = dim_flags(spec)
            spine[f"dim_{dim}_quality_flags"] = (
                spine["fiscal_period"].map(flags).fillna("[]")
            )
            spine[f"dim_{dim}_quality_ok"] = spine[f"dim_{dim}_quality_flags"].map(
                lambda raw: quality_ok(flags_from_storage(raw))
            )

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
