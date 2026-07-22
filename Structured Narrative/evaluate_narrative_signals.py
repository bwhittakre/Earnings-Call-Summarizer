#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward IC / RankIC evaluation for narrative modeling spine signals.

Labels (alpha_spec_{horizon}* / alpha_spec_asof_{horizon}*) are forward returns — never
model inputs. Call-date signals use call_feature_available_date; T+7 revision z uses
t7_feature_available_date and is only paired with labels that start on/after that date.

Cross-ticker investable as-of is recomputed on the stacked eval frame (per-ticker panels
alone set investable_as_of to each name's own T+7). Both as-of and event alpha labels are
then (re)built for every horizon in HORIZON_WINDOWS from cached specific returns.

Unit of observation: RankIC is computed separately for each (period, dimension)
cross-section (walk_forward_period_ics) — never pooling a company's eight dimension
rows (which share one forward return) into a single cross-section. As-of is the
primary/default cross-sectional test; event is grouped by earnings_date_calendar_quarter
(fiscal_period labels aren't calendar-aligned across companies) when retained.

    python "Structured Narrative/evaluate_narrative_signals.py"
    python "Structured Narrative/evaluate_narrative_signals.py" --labels both
    python "Structured Narrative/evaluate_narrative_signals.py" --tickers MSFT NVDA --include-delayed
    python "Structured Narrative/evaluate_narrative_signals.py" --horizons 0_14 0_56
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from asof_alpha import (  # noqa: E402
    ASOF_ALPHA_COLUMNS,
    EVENT_ALPHA_COLUMNS,
    HORIZON_WINDOWS,
    apply_asof_multi_horizon_labels,
    apply_event_multi_horizon_labels,
    asof_alpha_columns,
    event_alpha_columns,
    horizon_display_name,
)
from company_config import PILOT_OUTPUT_QUARTERS, PILOT_TICKERS  # noqa: E402
from composite_signal import (  # noqa: E402
    DEFAULT_MIN_PERIODS as COMPOSITE_DEFAULT_MIN_PERIODS,
    build_composite_signal,
    latest_composite_weights,
)
from export_modeling_spine import filter_registry_complete, load_panel  # noqa: E402
from fiscal_period_util import fiscal_period_sort_key  # noqa: E402
from output_paths import cross_company_artifact, ensure_cross_company_tree  # noqa: E402
from period_dates import (  # noqa: E402
    apply_feature_availability_dates,
    apply_investable_cross_section_columns,
    enrich_panel_period_columns,
    filter_min_calendar_quarter,
)
from quant_mapping import CALL_DATE_QUANT_DIMS  # noqa: E402
from rank_ic_html import (  # noqa: E402
    _period_ic_payload,
    build_rank_ic_report_html,
    company_period_signal_rows,
)
from spine_export import panel_to_spine, standardize_surprise_novelty_exclusivity  # noqa: E402

HORIZON_KEYS = [k for k, _a, _b, _n in HORIZON_WINDOWS]

# Legacy single-window columns — the only alpha_spec_* pair baked into the
# per-ticker feature_panel.csv on disk. Every other horizon is computed on the
# fly on the stacked cross-ticker frame (see load_eval_frame).
LABEL_COLUMNS = list(EVENT_ALPHA_COLUMNS) + list(ASOF_ALPHA_COLUMNS)

SIGNAL_COLUMNS = [
    "llm_level",
    "change_magnitude",
    "surprise_magnitude",
    "narrative_novelty",
    "quant_z_pit",
    "quant_guidance_revision_z_pit",
    "narrative_quant_gap",
    "agrees_with_quant",
    "evidence_confidence",
]

# Legacy back-compat single-label identifiers (the 0-90d window).
DEFAULT_LABEL = "alpha_spec_0_90"
EVENT_LABEL = "alpha_spec_0_90"
ASOF_LABEL = "alpha_spec_asof_0_90"

# Primary/default single-label block for back-compat top-level report fields.
PRIMARY_LABEL_FAMILY = "asof"
PRIMARY_HORIZON_KEY = "0_56"

CALL_DATE_SIGNALS = {
    "llm_level",
    "change_magnitude",
    "surprise_magnitude",
    "narrative_novelty",
    "quant_z_pit",
    "narrative_quant_gap",
    "agrees_with_quant",
    "evidence_confidence",
}

DELAYED_SIGNALS = {"quant_guidance_revision_z_pit"}

# Pre-specified primary hypotheses (superior's feedback, item 4), evaluated and
# reported SEPARATELY from the full exploratory signal × dimension × horizon
# grid, with its own multiple-testing (FDR) correction — see
# primary_hypothesis_report() / benjamini_hochberg(). The exploratory grid
# stays uncorrected (standard practice for a screening pass); only THIS
# pre-specified family gets the FDR treatment, per the plan.
PRIMARY_HYPOTHESES: tuple[dict[str, str], ...] = (
    {
        "signal": "quant_z_pit",
        "dimension": "demand",
        "hypothesis": "Demand quantitative z-score (quant_z_pit) predicts forward specific return",
    },
    {
        "signal": "agrees_with_quant",
        "dimension": "demand",
        "hypothesis": "Demand narrative/quantitative agreement predicts forward specific return",
    },
    {
        "signal": "agrees_with_quant",
        "dimension": "margins",
        "hypothesis": "Margins narrative/quantitative agreement predicts forward specific return",
    },
    {
        "signal": "agrees_with_quant",
        "dimension": "guidance",
        "hypothesis": "Guidance narrative/quantitative agreement predicts forward specific return",
    },
)


def is_primary_hypothesis(signal: str, dimension: str | None) -> bool:
    return any(h["signal"] == signal and h["dimension"] == dimension for h in PRIMARY_HYPOTHESES)


def _finite(x: Any) -> float | None:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(v) or math.isinf(v):
        return None
    return v


def _pearson_ic(x: pd.Series, y: pd.Series) -> float | None:
    mask = x.notna() & y.notna()
    if mask.sum() < 3:
        return None
    return _finite(x[mask].corr(y[mask], method="pearson"))


def _spearman_ic(x: pd.Series, y: pd.Series) -> float | None:
    mask = x.notna() & y.notna()
    if mask.sum() < 3:
        return None
    xr = x[mask].rank(method="average")
    yr = y[mask].rank(method="average")
    return _finite(xr.corr(yr, method="pearson"))


def walk_forward_period_ics(
    df: pd.DataFrame,
    signal: str,
    label: str,
    *,
    period_col: str = "fiscal_period",
    dimension_col: str = "dimension",
) -> pd.DataFrame:
    """Walk-forward IC/RankIC per (period, dimension) cross-section.

    Unit-of-observation fix: each ticker contributes exactly one row per
    (period, dimension) pair, so a cross-section here has at most one row per
    company — never one row per (company, dimension) pair sharing the same
    forward return. Compute per dimension separately (this function), then
    average across dimensions afterward if a cross-dimension summary is wanted
    (see evaluate_signals' dimension_mean) rather than pooling raw rows.
    """
    rows: list[dict] = []
    if period_col not in df.columns:
        return pd.DataFrame(rows)
    if period_col == "fiscal_period":
        periods = sorted(df[period_col].dropna().unique(), key=fiscal_period_sort_key)
    else:
        periods = sorted(df[period_col].dropna().astype(str).unique())
    has_dim = dimension_col in df.columns
    dimensions = sorted(df[dimension_col].dropna().astype(str).unique()) if has_dim else [None]

    for fp in periods:
        period_mask = df[period_col].astype(str) == str(fp)
        for dim in dimensions:
            if dim is None:
                sub = df[period_mask]
            else:
                sub = df[period_mask & (df[dimension_col].astype(str) == str(dim))]
            ic = _pearson_ic(sub[signal], sub[label])
            rank_ic = _spearman_ic(sub[signal], sub[label])
            if ic is None and rank_ic is None:
                continue
            rows.append(
                {
                    "fiscal_period": str(fp),
                    "period_col": period_col,
                    "dimension": dim,
                    "signal": signal,
                    "label": label,
                    "n": int(sub[[signal, label]].dropna().shape[0]),
                    "ic": ic,
                    "rank_ic": rank_ic,
                }
            )
    return pd.DataFrame(rows)


def summarize_ics(period_ics: pd.DataFrame) -> dict:
    if period_ics.empty:
        return {"n_periods": 0, "positive_rank_ic_periods": 0, "positive_rank_ic_hit_rate": None}
    ic = period_ics["ic"].dropna()
    rank = period_ics["rank_ic"].dropna()
    out: dict = {"n_periods": int(len(period_ics))}
    if len(ic):
        out["ic_mean"] = round(float(ic.mean()), 4)
        out["ic_std"] = round(float(ic.std(ddof=0)), 4) if len(ic) > 1 else None
        out["ic_ir"] = (
            round(float(ic.mean() / ic.std(ddof=0)), 4)
            if len(ic) > 1 and ic.std(ddof=0) > 0
            else None
        )
    if len(rank):
        out["rank_ic_mean"] = round(float(rank.mean()), 4)
        out["rank_ic_std"] = round(float(rank.std(ddof=0)), 4) if len(rank) > 1 else None
        out["rank_ic_ir"] = (
            round(float(rank.mean() / rank.std(ddof=0)), 4)
            if len(rank) > 1 and rank.std(ddof=0) > 0
            else None
        )
        pos = int((rank > 0).sum())
        out["positive_rank_ic_periods"] = pos
        out["positive_rank_ic_hit_rate"] = round(pos / len(rank), 4)
    else:
        out["positive_rank_ic_periods"] = 0
        out["positive_rank_ic_hit_rate"] = None
    return out


def quintile_spread(df: pd.DataFrame, signal: str, label: str, n_q: int = 5) -> dict:
    sub = df[[signal, label]].dropna()
    if len(sub) < n_q * 2:
        return {"n": int(len(sub)), "spread": None}
    try:
        sub = sub.copy()
        sub["q"] = pd.qcut(sub[signal], n_q, labels=False, duplicates="drop")
    except ValueError:
        return {"n": int(len(sub)), "spread": None}
    means = sub.groupby("q")[label].mean()
    if len(means) < 2:
        return {"n": int(len(sub)), "spread": None}
    return {
        "n": int(len(sub)),
        "spread_top_minus_bottom": round(float(means.iloc[-1] - means.iloc[0]), 6),
        "quintile_means": [round(float(v), 6) for v in means.tolist()],
    }


def divergence_hit_rate(df: pd.DataFrame, label: str) -> dict:
    """Legacy pooled agree/disagree mean-return check (see agreement_effect_stats for the CI)."""
    sub = df[df["agrees_with_quant"].notna() & df[label].notna()].copy()
    if sub.empty:
        return {"n": 0}
    div = sub[sub["agrees_with_quant"] == False]  # noqa: E712
    agree = sub[sub["agrees_with_quant"] == True]  # noqa: E712
    return {
        "n_total": int(len(sub)),
        "n_divergence": int(len(div)),
        "n_agree": int(len(agree)),
        "mean_label_divergence": round(float(div[label].mean()), 6) if len(div) else None,
        "mean_label_agree": round(float(agree[label].mean()), 6) if len(agree) else None,
    }


def _cluster_key_series(df: pd.DataFrame, cluster_col: str) -> pd.Series:
    """Map a logical cluster key to the resampling-unit series for that key.

    "ticker"          -- resample companies (the original default: every row
                          belonging to a company, across every period AND
                          every dimension it appears in, moves together).
    "calendar_period"  -- resample calendar periods (robustness check: is a
                          result driven by a handful of volatile quarters
                          rather than being broadly true across time?).
    "company_period"  -- resample (ticker, period) pairs -- the finest unit
                          that still keeps one company-period's repeated rows
                          (e.g. its 8 dimension rows, which all share the same
                          forward return) together in one cluster, avoiding
                          the double-counting the RankIC unit-of-observation
                          fix addresses even when the statistic pools rows
                          across dimensions or periods.
    """
    if cluster_col == "ticker":
        return df["ticker"].astype(str).str.upper()
    period_col = "period_end_calendar_quarter" if "period_end_calendar_quarter" in df.columns else "fiscal_period"
    if cluster_col == "calendar_period":
        return df[period_col].astype(str)
    if cluster_col == "company_period":
        return df["ticker"].astype(str).str.upper() + "::" + df[period_col].astype(str)
    raise ValueError(f"Unknown cluster_col {cluster_col!r} (expected ticker/calendar_period/company_period)")


def cluster_bootstrap_mean_diff(
    df: pd.DataFrame,
    group_col: str,
    value_col: str,
    *,
    cluster_col: str = "ticker",
    n_boot: int = 2000,
    seed: int = 13,
) -> dict:
    """Cluster-bootstrap CI + two-sided p-value for mean(group=True) - mean(group=False).

    Resamples whole clusters (see _cluster_key_series), not individual rows, so
    a company's (or period's) repeated rows always move together and are never
    treated as independent observations they aren't. Generalizes the original
    ticker-only bootstrap in agreement_effect_stats to any of the three cluster
    keys the build plan calls for.
    """
    sub = df[[group_col, value_col]].copy()
    sub["_cluster"] = _cluster_key_series(df, cluster_col).values
    sub = sub.dropna(subset=[group_col, value_col, "_cluster"])
    out: dict = {
        "cluster_col": cluster_col,
        "n_clusters": 0,
        "mean_diff": None,
        "ci_low": None,
        "ci_high": None,
        "p_value": None,
        "n_boot": n_boot,
        "n_boot_used": 0,
    }
    if sub.empty:
        return out
    true_mean = sub.loc[sub[group_col] == True, value_col].mean()  # noqa: E712
    false_mean = sub.loc[sub[group_col] == False, value_col].mean()  # noqa: E712
    clusters = sorted(sub["_cluster"].unique())
    out["n_clusters"] = len(clusters)
    if pd.isna(true_mean) or pd.isna(false_mean):
        return out
    observed = float(true_mean - false_mean)
    out["mean_diff"] = round(observed, 6)
    if len(clusters) < 2:
        return out

    rng = np.random.default_rng(seed)
    groups = {c: g for c, g in sub.groupby("_cluster")}
    boot_diffs: list[float] = []
    for _ in range(n_boot):
        sample = rng.choice(clusters, size=len(clusters), replace=True)
        resampled = pd.concat([groups[c] for c in sample], ignore_index=True)
        r_true = resampled.loc[resampled[group_col] == True, value_col].mean()  # noqa: E712
        r_false = resampled.loc[resampled[group_col] == False, value_col].mean()  # noqa: E712
        if pd.isna(r_true) or pd.isna(r_false):
            continue
        boot_diffs.append(float(r_true - r_false))
    out["n_boot_used"] = len(boot_diffs)
    if out["n_boot_used"] < max(50, n_boot // 4):
        return out
    arr = np.array(boot_diffs)
    out["ci_low"] = round(float(np.percentile(arr, 2.5)), 6)
    out["ci_high"] = round(float(np.percentile(arr, 97.5)), 6)
    # Two-sided bootstrap p-value: proportion of the resampled distribution on
    # the opposite side of zero from the observed sign, doubled and capped at 1.
    if observed >= 0:
        p = 2.0 * min(1.0, float((arr <= 0).mean()))
    else:
        p = 2.0 * min(1.0, float((arr >= 0).mean()))
    out["p_value"] = round(min(p, 1.0), 6)
    return out


def bootstrap_rank_ic_mean(period_ics: pd.DataFrame, *, n_boot: int = 2000, seed: int = 13) -> dict:
    """Cluster-bootstrap CI + two-sided p-value for a walk-forward RankIC mean.

    Each row of ``period_ics`` (from walk_forward_period_ics) is already one
    independent, unit-correct cross-section — so the cluster here is the
    PERIOD itself; resampling periods (not underlying rows) is the correct
    way to test whether the mean RankIC is distinguishable from zero.
    """
    vals = period_ics["rank_ic"].dropna().to_numpy() if not period_ics.empty else np.array([])
    out = {"n_periods": int(len(vals)), "mean": None, "ci_low": None, "ci_high": None, "p_value": None, "n_boot": n_boot}
    if len(vals) < 3:
        return out
    observed = float(vals.mean())
    out["mean"] = round(observed, 4)
    rng = np.random.default_rng(seed)
    boot_means = rng.choice(vals, size=(n_boot, len(vals)), replace=True).mean(axis=1)
    out["ci_low"] = round(float(np.percentile(boot_means, 2.5)), 4)
    out["ci_high"] = round(float(np.percentile(boot_means, 97.5)), 4)
    if observed >= 0:
        p = 2.0 * min(1.0, float((boot_means <= 0).mean()))
    else:
        p = 2.0 * min(1.0, float((boot_means >= 0).mean()))
    out["p_value"] = round(min(p, 1.0), 6)
    return out


def benjamini_hochberg(p_values: list[float | None], *, alpha: float = 0.05) -> list[dict]:
    """Benjamini-Hochberg FDR correction, returned in the ORIGINAL input order.

    ``None`` entries (missing/undefined tests) pass through with q_value=None,
    reject=False, and are excluded from the correction's multiple-testing
    count entirely (they were never a test in the first place).
    """
    m = sum(1 for p in p_values if p is not None)
    result: list[dict] = [{"p_value": p, "q_value": None, "reject": False} for p in p_values]
    if m == 0:
        return result
    indexed = sorted(
        ((i, p) for i, p in enumerate(p_values) if p is not None), key=lambda t: t[1]
    )
    q_running = 1.0
    q_by_index: dict[int, float] = {}
    for rank in range(m, 0, -1):
        i_orig, p = indexed[rank - 1]
        q_running = min(q_running, p * m / rank)
        q_by_index[i_orig] = q_running
    for i_orig, p in indexed:
        q = q_by_index[i_orig]
        result[i_orig] = {"p_value": p, "q_value": round(float(q), 6), "reject": bool(q <= alpha)}
    return result


def primary_hypothesis_rows(
    period_df: pd.DataFrame,
    agreement_rows_for_tag: list[dict],
    *,
    fam: str,
    horizon: str,
    n_boot: int = 2000,
) -> list[dict]:
    """One row per PRIMARY_HYPOTHESES entry for this (label, horizon) tag.

    quant_z_pit hypotheses are tested via a period-cluster bootstrap on the
    walk-forward RankIC mean (bootstrap_rank_ic_mean); agrees_with_quant
    hypotheses reuse the ticker-cluster bootstrap already computed per
    dimension in agreement_effect_stats (agreement_rows_for_tag). p_value
    here is per-test — benjamini_hochberg() is applied once, across every
    (label, horizon, hypothesis) row, by the caller in main().
    """
    rows: list[dict] = []
    for h in PRIMARY_HYPOTHESES:
        base = {
            "label_key": fam,
            "horizon": horizon,
            "signal": h["signal"],
            "dimension": h["dimension"],
            "hypothesis": h["hypothesis"],
        }
        if h["signal"] == "agrees_with_quant":
            match = next(
                (r for r in agreement_rows_for_tag if r.get("dimension") == h["dimension"]), None
            )
            if match is None:
                rows.append({**base, "stat": None, "n": None, "p_value": None})
                continue
            rows.append(
                {
                    **base,
                    "stat": match.get("spread"),
                    "ci_low": match.get("ci_low"),
                    "ci_high": match.get("ci_high"),
                    "n": match.get("n_agree", 0) + match.get("n_disagree", 0),
                    "n_clusters": match.get("n_tickers"),
                    "p_value": match.get("p_value"),
                }
            )
        else:
            sub = period_df[
                (period_df.get("signal") == h["signal"]) & (period_df.get("dimension") == h["dimension"])
            ] if not period_df.empty else pd.DataFrame()
            boot = bootstrap_rank_ic_mean(sub, n_boot=n_boot)
            rows.append(
                {
                    **base,
                    "stat": boot.get("mean"),
                    "ci_low": boot.get("ci_low"),
                    "ci_high": boot.get("ci_high"),
                    "n": boot.get("n_periods"),
                    "n_clusters": boot.get("n_periods"),
                    "p_value": boot.get("p_value"),
                }
            )
    return rows


def agreement_effect_stats(
    df: pd.DataFrame,
    label: str,
    *,
    dimension: str | None = None,
    n_boot: int = 2000,
    seed: int = 13,
    cluster_col: str = "ticker",
) -> dict:
    """Mean forward return by agrees_with_quant (True/False), spread, and a 95% CI.

    agrees_with_quant is a categorical, dimension-scoped flag that repeats across
    periods for the same company (and, when ``dimension`` is None, across the
    pooled quant-mapped dimensions too) — the same pseudo-replication issue the
    RankIC unit-of-observation fix addresses. cluster_bootstrap_mean_diff resamples
    whole clusters (default: the *ticker set*) with replacement, so every company
    is one independent unit regardless of how many rows it contributes. With only
    a handful of tickers the resulting CI will be wide — that reflects genuinely
    limited cross-sectional power, not a bug in the method.
    """
    sub = df[df["agrees_with_quant"].notna() & df[label].notna()].copy()
    if dimension is not None and "dimension" in sub.columns:
        sub = sub[sub["dimension"].astype(str) == dimension]
    dim_tag = dimension or "pooled"
    if sub.empty:
        return {
            "dimension": dim_tag,
            "n_agree": 0,
            "n_disagree": 0,
            "n_tickers": 0,
            "mean_return_agree": None,
            "mean_return_disagree": None,
            "spread": None,
            "ci_low": None,
            "ci_high": None,
            "p_value": None,
            "n_boot": n_boot,
            "cluster_col": cluster_col,
        }

    agree = sub[sub["agrees_with_quant"] == True]  # noqa: E712
    disagree = sub[sub["agrees_with_quant"] == False]  # noqa: E712
    mean_agree = float(agree[label].mean()) if len(agree) else None
    mean_disagree = float(disagree[label].mean()) if len(disagree) else None

    boot = cluster_bootstrap_mean_diff(
        sub, "agrees_with_quant", label, cluster_col=cluster_col, n_boot=n_boot, seed=seed
    )
    n_tickers = int(sub["ticker"].astype(str).str.upper().nunique())

    return {
        "dimension": dim_tag,
        "n_agree": int(len(agree)),
        "n_disagree": int(len(disagree)),
        "n_tickers": n_tickers,
        "mean_return_agree": round(mean_agree, 6) if mean_agree is not None else None,
        "mean_return_disagree": round(mean_disagree, 6) if mean_disagree is not None else None,
        "spread": boot.get("mean_diff"),
        "ci_low": boot.get("ci_low"),
        "ci_high": boot.get("ci_high"),
        "p_value": boot.get("p_value"),
        "n_boot": n_boot,
        "n_boot_used": boot.get("n_boot_used", 0),
        "cluster_col": cluster_col,
    }


def load_eval_frame(
    tickers: list[str],
    *,
    call_date_only: bool = True,
    quarters: list[str] | None = None,
    min_calendar_quarter: str | None = None,
    recompute_cross_ticker_asof: bool = True,
    fetch_returns_if_missing: bool = True,
    horizons: list[str] | None = None,
) -> pd.DataFrame:
    """Stack panels and rebuild cross-ticker investable as-of + multi-horizon alpha labels.

    ``quarters=None`` means no fiscal-period filter — use each ticker's full
    registry-complete history (still per-ticker, since fiscal calendars aren't
    aligned across companies). Combine with ``min_calendar_quarter`` to get a
    calendar-aligned N-year window across the whole universe, mirroring how
    build_consolidated_panel_report.py trims AMZN's longer history.
    """
    quarter_set = set(quarters) if quarters else None
    windows = [w for w in HORIZON_WINDOWS if w[0] in horizons] if horizons else list(HORIZON_WINDOWS)
    frames: list[pd.DataFrame] = []
    for ticker in tickers:
        panel = load_panel(ticker)
        panel = filter_registry_complete(panel, ticker)
        if quarter_set is not None:
            panel = panel[panel["fiscal_period"].isin(quarter_set)].copy()
        panel = standardize_surprise_novelty_exclusivity(panel)
        panel = enrich_panel_period_columns(panel)
        if min_calendar_quarter:
            panel = filter_min_calendar_quarter(panel, min_calendar_quarter)
        if panel.empty:
            continue
        if "call_feature_available_date" not in panel.columns:
            panel = apply_feature_availability_dates(panel)
        spine = panel_to_spine(panel)
        for c in LABEL_COLUMNS:
            if c in panel.columns:
                spine[c] = panel[c].values
        for c in (
            "investable_as_of_date",
            "days_since_earnings",
            "feature_age_days",
            "investable_ready",
            "period_end_calendar_quarter",
            "earnings_date_calendar_quarter",
            "model_date",
        ):
            if c in panel.columns and c not in spine.columns:
                spine[c] = panel[c].values
        frames.append(spine)
    if not frames:
        raise FileNotFoundError("No feature panels loaded.")
    stacked = pd.concat(frames, ignore_index=True)
    stacked = stacked.sort_values(["ticker", "fiscal_period", "dimension"]).reset_index(drop=True)

    if "earnings_date_calendar_quarter" not in stacked.columns:
        stacked = enrich_panel_period_columns(stacked)

    if recompute_cross_ticker_asof:
        # Drop per-ticker investable columns before cross-ticker rebuild.
        for c in ("investable_as_of_date", "days_since_earnings", "feature_age_days", "investable_ready"):
            if c in stacked.columns:
                stacked = stacked.drop(columns=[c])
        stacked = apply_investable_cross_section_columns(stacked)
        stacked = apply_asof_multi_horizon_labels(
            stacked, windows=windows, fetch_if_missing=fetch_returns_if_missing
        )
        stacked = apply_event_multi_horizon_labels(
            stacked, windows=windows, fetch_if_missing=fetch_returns_if_missing
        )

    if call_date_only:
        call_col = (
            "call_feature_available_date"
            if "call_feature_available_date" in stacked.columns
            else "feature_availability_date"
        )
        stacked = stacked[
            stacked[call_col].astype(str).str[:10] == stacked["earnings_date"].astype(str).str[:10]
        ].copy()
    return stacked


def _signal_eval_frame(df: pd.DataFrame, signal: str) -> pd.DataFrame:
    """Restrict delayed revision signals to rows with T+7 availability."""
    if signal not in DELAYED_SIGNALS:
        return df
    out = df[df[signal].notna()].copy()
    if "t7_feature_available_date" in out.columns:
        out = out[out["t7_feature_available_date"].notna()].copy()
    return out


def evaluate_signals(
    df: pd.DataFrame,
    signals: list[str],
    label: str,
    *,
    period_col: str = "fiscal_period",
    universe: str = "all",
) -> tuple[dict[str, dict], pd.DataFrame]:
    """Return per-signal, per-dimension walk-forward stats and concatenated period-IC rows.

    Unit-of-observation fix: RankIC is computed separately for each (period,
    dimension) cross-section (walk_forward_period_ics), so a company never
    contributes more than one observation to any single cross-section.
    ``by_dimension`` holds each dimension's own walk-forward summary plus pooled
    (all-periods-for-that-dimension) stats and quintile spread; ``dimension_mean``
    averages the per-dimension walk-forward RankIC means — a valid summary
    because every ingredient is itself unit-correct (unlike the old
    cross-dimension-pooled RankIC, which mixed a company's 8 dimension rows,
    each pointing at the same forward return, into one cross-section).
    """
    if label not in df.columns:
        return {}, pd.DataFrame()
    eval_df = df[df[label].notna()].copy()
    signal_summary: dict[str, dict] = {}
    period_frames: list[pd.DataFrame] = []

    for signal in signals:
        if signal not in eval_df.columns:
            continue
        sig_df = _signal_eval_frame(eval_df, signal)
        if sig_df.empty:
            continue
        period_ics = walk_forward_period_ics(sig_df, signal, label, period_col=period_col)
        if not period_ics.empty:
            period_ics = period_ics.copy()
            period_ics["universe"] = universe
            period_frames.append(period_ics)

        by_dimension: dict[str, dict] = {}
        dims = (
            sorted(sig_df["dimension"].dropna().astype(str).unique())
            if "dimension" in sig_df.columns
            else []
        )
        for dim in dims:
            dim_df = sig_df[sig_df["dimension"].astype(str) == dim]
            dim_period_ics = (
                period_ics[period_ics["dimension"].astype(str) == dim]
                if not period_ics.empty
                else pd.DataFrame()
            )
            by_dimension[dim] = {
                "walk_forward": summarize_ics(dim_period_ics),
                "pooled_ic": _pearson_ic(dim_df[signal], dim_df[label]),
                "pooled_rank_ic": _spearman_ic(dim_df[signal], dim_df[label]),
                "quintile_spread": quintile_spread(dim_df, signal, label),
                "n_rows": int(dim_df[[signal, label]].dropna().shape[0]),
            }

        dim_means = [
            v["walk_forward"].get("rank_ic_mean")
            for v in by_dimension.values()
            if v["walk_forward"].get("rank_ic_mean") is not None
        ]
        dimension_mean = {
            "rank_ic_mean": round(float(np.mean(dim_means)), 4) if dim_means else None,
            "n_dimensions": len(dim_means),
        }

        signal_summary[signal] = {
            "by_dimension": by_dimension,
            "dimension_mean": dimension_mean,
            "n_rows": int(sig_df[[signal, label]].dropna().shape[0]),
            "availability": (
                "t7_feature_available_date"
                if signal in DELAYED_SIGNALS
                else "call_feature_available_date"
            ),
            "label": label,
            "universe": universe,
            "period_col": period_col,
        }

    period_df = pd.concat(period_frames, ignore_index=True) if period_frames else pd.DataFrame()
    return signal_summary, period_df


def leave_one_ticker_out(
    df: pd.DataFrame,
    signals: list[str],
    label: str,
    *,
    period_col: str = "fiscal_period",
    universe: str = "all",
) -> list[dict]:
    """Jackknife: per-dimension walk-forward RankIC mean with each ticker held out.

    Sample sizes shrink fast here — dropping one of ≤4 tickers from an
    already-corrected (≤4-point) per-dimension cross-section can leave too few
    points for a given period (_spearman_ic requires n≥3), so some periods will
    legitimately drop out. That's expected sparsity from the fix, not a bug.
    """
    tickers = sorted(df["ticker"].dropna().astype(str).str.upper().unique())
    rows: list[dict] = []
    for held in tickers:
        sub = df[df["ticker"].astype(str).str.upper() != held]
        summary, _ = evaluate_signals(
            sub, signals, label, period_col=period_col, universe=universe
        )
        for signal, stats in summary.items():
            by_dimension = stats.get("by_dimension") or {}
            for dim, dim_stats in by_dimension.items():
                wf = dim_stats.get("walk_forward", {})
                rows.append(
                    {
                        "held_out_ticker": held,
                        "signal": signal,
                        "label": label,
                        "dimension": dim,
                        "universe": universe,
                        "rank_ic_mean": wf.get("rank_ic_mean"),
                        "rank_ic_ir": wf.get("rank_ic_ir"),
                        "pooled_rank_ic": _finite(dim_stats.get("pooled_rank_ic")),
                        "n_periods": wf.get("n_periods"),
                        "n_rows": dim_stats.get("n_rows"),
                    }
                )
    return rows


def leaderboard_rows(label_blocks: dict[str, dict[str, dict[str, dict]]]) -> list[dict]:
    """Flatten label × horizon × signal × dimension summaries into leaderboard rows.

    Each row is one (label family, horizon, signal, dimension) walk-forward
    result — the corrected unit of observation. A synthetic "ALL_MEAN" dimension
    row is also included per (label, horizon, signal): the average of that
    signal's per-dimension RankIC means, for a quick cross-dimension glance.
    """
    rows: list[dict] = []
    for label_key, horizon_blocks in label_blocks.items():
        for horizon_key, signals in horizon_blocks.items():
            for signal, stats in signals.items():
                by_dimension = stats.get("by_dimension") or {}
                for dim, dim_stats in by_dimension.items():
                    wf = dim_stats.get("walk_forward", {})
                    rows.append(
                        {
                            "signal": signal,
                            "label": label_key,
                            "horizon": horizon_key,
                            "horizon_name": horizon_display_name(horizon_key),
                            "dimension": dim,
                            "universe": stats.get("universe"),
                            "rank_ic_mean": wf.get("rank_ic_mean"),
                            "rank_ic_ir": wf.get("rank_ic_ir"),
                            "pooled_rank_ic": _finite(dim_stats.get("pooled_rank_ic")),
                            "positive_rank_ic_hit_rate": wf.get("positive_rank_ic_hit_rate"),
                            "n_periods": wf.get("n_periods"),
                            "n_rows": dim_stats.get("n_rows"),
                            "is_primary": is_primary_hypothesis(signal, dim),
                        }
                    )
                dm = stats.get("dimension_mean") or {}
                rows.append(
                    {
                        "signal": signal,
                        "label": label_key,
                        "horizon": horizon_key,
                        "horizon_name": horizon_display_name(horizon_key),
                        "dimension": "ALL_MEAN",
                        "universe": stats.get("universe"),
                        "rank_ic_mean": dm.get("rank_ic_mean"),
                        "rank_ic_ir": None,
                        "pooled_rank_ic": None,
                        "positive_rank_ic_hit_rate": None,
                        "n_periods": dm.get("n_dimensions"),
                        "n_rows": stats.get("n_rows"),
                        "is_primary": False,
                    }
                )
    rows.sort(
        key=lambda r: (
            r["label"],
            r["horizon"],
            -(r["rank_ic_mean"] if r["rank_ic_mean"] is not None else -999),
            r["signal"],
            r["dimension"],
        )
    )
    return rows


def cross_section_counts(df: pd.DataFrame, period_col: str) -> dict[str, int]:
    """Distinct ticker count per period value — the actual cross-section size
    behind every RankIC number (item 7: "the number of companies in each
    quarterly cross-section"). A RankIC computed over n=2 companies means
    something very different from one computed over n=16; this makes that
    visible next to every result rather than only in n_rows/n_periods, which
    conflate cross-section size with period count.
    """
    if period_col not in df.columns or "ticker" not in df.columns:
        return {}
    counts = df.groupby(period_col)["ticker"].nunique()
    return {str(k): int(v) for k, v in counts.items()}


def apply_dev_holdout_split(
    df: pd.DataFrame,
    period_col: str,
    *,
    dev_cutoff: str | None = None,
    holdout_start: str | None = None,
    holdout_only: bool = False,
    dev_only: bool = False,
) -> pd.DataFrame:
    """Split the eval frame into a development window vs. a genuine holdout.

    ``dev_cutoff`` / ``holdout_start`` are calendar-quarter strings (e.g.
    "2023-Q1"), compared via calendar_quarter_sort_key so they work regardless
    of period_col's exact format (period_end_calendar_quarter or
    earnings_date_calendar_quarter).

    When only ONE bound is given, the other window is its implied complement
    (dev_cutoff alone => holdout is everything strictly after it; holdout_start
    alone => dev is everything strictly before it) -- so passing just
    --dev-cutoff, with no --*-only flag, filters the frame down to that dev
    window's complement being dropped nowhere and everything partitioned, not
    silently returning the full frame. When BOTH are given, rows strictly
    between them are dropped so the two windows don't overlap.
    holdout_only/dev_only restrict the result to just one side.
    """
    if not (dev_cutoff or holdout_start) or period_col not in df.columns:
        return df
    from period_dates import calendar_quarter_sort_key

    if dev_only and holdout_only:
        raise ValueError("dev_only and holdout_only are mutually exclusive.")

    keys = df[period_col].astype(str).map(calendar_quarter_sort_key)
    cutoff_key = calendar_quarter_sort_key(dev_cutoff) if dev_cutoff else None
    start_key = calendar_quarter_sort_key(holdout_start) if holdout_start else None

    if cutoff_key is not None:
        dev_mask = keys <= cutoff_key
    else:
        dev_mask = keys < start_key  # implied complement of holdout_start
    if start_key is not None:
        holdout_mask = keys >= start_key
    else:
        holdout_mask = keys > cutoff_key  # implied complement of dev_cutoff

    if dev_only:
        return df[dev_mask].copy()
    if holdout_only:
        return df[holdout_mask].copy()
    # No explicit only-filter: keep dev ∪ holdout, dropping any no-man's-land
    # strictly between an explicit dev_cutoff and holdout_start.
    return df[dev_mask | holdout_mask].copy()


def label_overlap_stats(df: pd.DataFrame) -> dict:
    """How often the legacy 0-90d event vs asof alphas differ after cross-ticker rebuild."""
    if EVENT_LABEL not in df.columns or ASOF_LABEL not in df.columns:
        return {}
    both = df[df[EVENT_LABEL].notna() & df[ASOF_LABEL].notna()]
    if both.empty:
        return {"n_both": 0}
    diff = (both[EVENT_LABEL] - both[ASOF_LABEL]).abs()
    return {
        "n_both": int(len(both)),
        "n_equal": int((diff < 1e-12).sum()),
        "n_differ": int((diff >= 1e-12).sum()),
        "max_abs_diff": round(float(diff.max()), 6) if len(diff) else None,
        "mean_abs_diff": round(float(diff.mean()), 6) if len(diff) else None,
    }


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        if math.isnan(v) or math.isinf(v):
            return None
        return v
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def main() -> int:
    ap = argparse.ArgumentParser(description="Walk-forward IC/RankIC for narrative signals.")
    ap.add_argument("--tickers", nargs="+", default=list(PILOT_TICKERS))
    ap.add_argument(
        "--label",
        default=None,
        help="Single label column (legacy escape hatch). Prefer --labels/--horizons.",
    )
    ap.add_argument(
        "--labels",
        choices=("event", "asof", "both"),
        default="asof",
        help=(
            "Which forward-label set(s) to evaluate (default: asof — the primary "
            "cross-sectional test; fiscal-quarter labels aren't calendar-aligned "
            "across companies, so 'event' is grouped by earnings_date_calendar_quarter "
            "when included)."
        ),
    )
    ap.add_argument(
        "--horizons",
        nargs="+",
        choices=HORIZON_KEYS,
        default=list(HORIZON_KEYS),
        help="Forward-return horizons to evaluate (default: all — see asof_alpha.HORIZON_WINDOWS).",
    )
    ap.add_argument(
        "--include-delayed",
        action="store_true",
        help="Include T+7d guidance revision z; pairs with t+7-entry labels only.",
    )
    ap.add_argument(
        "--signals",
        nargs="+",
        default=None,
        help="Panel columns to evaluate as signals.",
    )
    ap.add_argument(
        "--quarters",
        nargs="+",
        default=None,
        help=(
            "Fiscal periods to include (default: PILOT_OUTPUT_QUARTERS, unless "
            "--min-calendar-quarter is given without an explicit --quarters, in "
            "which case each ticker's full registry-complete history is used and "
            "trimmed by calendar quarter instead — e.g. for a 5-year cross-company "
            "window)."
        ),
    )
    ap.add_argument(
        "--min-calendar-quarter",
        metavar="yyyy-Qn",
        help="Drop rows before this period-end calendar quarter (e.g. 2021-Q3).",
    )
    ap.add_argument(
        "--investable-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For as-of label: restrict to investable_ready rows (default: true).",
    )
    ap.add_argument(
        "--jackknife",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Leave-one-ticker-out RankIC means (default: true).",
    )
    ap.add_argument(
        "--agreement-bootstrap",
        type=int,
        default=2000,
        help="Ticker-cluster bootstrap resamples for the agreement-effect CI (default: 2000).",
    )
    ap.add_argument(
        "--composite",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Evaluate a walk-forward, PIT-correct composite_score per dimension "
            "that blends the raw signals using expanding, strictly-prior-period "
            "fitted weights (default: true). See composite_signal.py."
        ),
    )
    ap.add_argument(
        "--composite-min-periods",
        type=int,
        default=COMPOSITE_DEFAULT_MIN_PERIODS,
        help=(
            f"Distinct prior periods required before composite_score is defined "
            f"for a dimension (default: {COMPOSITE_DEFAULT_MIN_PERIODS})."
        ),
    )
    ap.add_argument(
        "--no-recompute-asof",
        action="store_true",
        help="Skip cross-ticker investable rebuild / multi-horizon alpha recompute.",
    )
    ap.add_argument(
        "--primary-hypothesis-bootstrap",
        type=int,
        default=2000,
        help="Bootstrap resamples for the primary-hypothesis significance tests (default: 2000).",
    )
    ap.add_argument(
        "--fdr-alpha",
        type=float,
        default=0.05,
        help="Benjamini-Hochberg FDR threshold applied to the primary hypothesis family (default: 0.05).",
    )
    ap.add_argument(
        "--dev-cutoff",
        metavar="yyyy-Qn",
        default=None,
        help=(
            "Development window ends at (and includes) this calendar quarter, e.g. 2023-Q1. "
            "Combine with --holdout-start to define a real out-of-sample split; see item 5 of the "
            "Structured Narrative Expansion plan."
        ),
    )
    ap.add_argument(
        "--holdout-start",
        metavar="yyyy-Qn",
        default=None,
        help="Holdout window starts at (and includes) this calendar quarter, e.g. 2023-Q2.",
    )
    dev_holdout_group = ap.add_mutually_exclusive_group()
    dev_holdout_group.add_argument(
        "--dev-only", action="store_true", help="Evaluate only rows at/before --dev-cutoff."
    )
    dev_holdout_group.add_argument(
        "--holdout-only", action="store_true", help="Evaluate only rows at/after --holdout-start."
    )
    args = ap.parse_args()
    tickers = [t.upper() for t in args.tickers]
    signals = args.signals or list(SIGNAL_COLUMNS)
    if not args.include_delayed:
        signals = [s for s in signals if s in CALL_DATE_SIGNALS]

    horizon_keys = list(dict.fromkeys(args.horizons)) or list(HORIZON_KEYS)

    if args.quarters:
        quarters_filter: list[str] | None = list(args.quarters)
    elif args.min_calendar_quarter:
        quarters_filter = None  # full per-ticker history, trimmed by calendar quarter below
    else:
        quarters_filter = list(PILOT_OUTPUT_QUARTERS)

    # Legacy --label overrides --labels/--horizons to a single custom column.
    if args.label:
        label_specs = [("custom", "custom", args.label, "all", "fiscal_period")]
    else:
        label_families = []
        if args.labels in ("event", "both"):
            label_families.append("event")
        if args.labels in ("asof", "both"):
            label_families.append("asof")
        label_specs = []
        for fam in label_families:
            for hk in horizon_keys:
                if fam == "event":
                    label_specs.append(
                        (fam, hk, event_alpha_columns(hk)[0], "all", "earnings_date_calendar_quarter")
                    )
                else:
                    univ = "investable_ready" if args.investable_only else "all"
                    label_specs.append(
                        (fam, hk, asof_alpha_columns(hk)[0], univ, "period_end_calendar_quarter")
                    )

    try:
        df = load_eval_frame(
            tickers,
            call_date_only=not args.include_delayed,
            quarters=quarters_filter,
            min_calendar_quarter=args.min_calendar_quarter,
            recompute_cross_ticker_asof=not args.no_recompute_asof,
            horizons=horizon_keys,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    label_blocks: dict[str, dict[str, dict[str, dict]]] = {}
    period_frames: list[pd.DataFrame] = []
    jackknife_rows: list[dict] = []
    divergence_by_label: dict[str, dict] = {}
    agreement_rows: list[dict] = []
    n_rows_by_label: dict[str, int] = {}
    company_period_rows: list[dict] = []
    composite_weights_by_label: dict[str, dict] = {}
    cross_section_counts_by_label: dict[str, dict[str, int]] = {}
    primary_hypothesis_raw: list[dict] = []

    for fam, hk, label, universe, period_col in label_specs:
        if label not in df.columns or df[label].notna().sum() == 0:
            print(f"Warning: label {label!r} missing or empty — skipping.", file=sys.stderr)
            continue
        work = df
        if universe == "investable_ready":
            if "investable_ready" not in work.columns:
                print("Warning: investable_ready missing — using all rows for as-of.", file=sys.stderr)
            else:
                work = work[work["investable_ready"] == True].copy()  # noqa: E712
        pcol = period_col if period_col in work.columns else "fiscal_period"
        tag = f"{fam}:{hk}"

        work = apply_dev_holdout_split(
            work,
            pcol,
            dev_cutoff=args.dev_cutoff,
            holdout_start=args.holdout_start,
            holdout_only=args.holdout_only,
            dev_only=args.dev_only,
        )

        eval_signals = list(signals)
        if args.composite:
            work = work.copy()
            work["composite_score"] = build_composite_signal(
                work,
                label,
                period_col=pcol,
                min_periods=args.composite_min_periods,
            )
            eval_signals = eval_signals + ["composite_score"]
            composite_weights_by_label[tag] = latest_composite_weights(
                work,
                label,
                period_col=pcol,
                min_periods=args.composite_min_periods,
            )

        summary, period_df = evaluate_signals(
            work, eval_signals, label, period_col=pcol, universe=universe
        )
        label_blocks.setdefault(fam, {})[hk] = summary
        n_rows_by_label[tag] = int(work[label].notna().sum())
        divergence_by_label[tag] = divergence_hit_rate(work, label)

        if not period_df.empty:
            period_df = period_df.copy()
            period_df["label_key"] = fam
            period_df["horizon"] = hk
            period_frames.append(period_df)

        company_period_rows.extend(
            company_period_signal_rows(
                work,
                eval_signals,
                label,
                period_col=pcol,
                label_key=fam,
                universe=universe,
                horizon=hk,
            )
        )

        if args.jackknife and len(tickers) > 1:
            jrows = leave_one_ticker_out(work, eval_signals, label, period_col=pcol, universe=universe)
            for r in jrows:
                r["label_key"] = fam
                r["horizon"] = hk
            jackknife_rows.extend(jrows)

        tag_agreement_rows: list[dict] = []
        for dim in list(CALL_DATE_QUANT_DIMS) + [None]:
            stats = agreement_effect_stats(
                work, label, dimension=dim, n_boot=args.agreement_bootstrap
            )
            stats["label_key"] = fam
            stats["horizon"] = hk
            stats["horizon_name"] = horizon_display_name(hk)
            tag_agreement_rows.append(stats)
        agreement_rows.extend(tag_agreement_rows)

        cross_section_counts_by_label[tag] = cross_section_counts(work, pcol)
        primary_hypothesis_raw.extend(
            primary_hypothesis_rows(
                period_df,
                tag_agreement_rows,
                fam=fam,
                horizon=hk,
                n_boot=args.primary_hypothesis_bootstrap,
            )
        )

    if not label_blocks:
        print("Error: no labels evaluated.", file=sys.stderr)
        return 1

    board = leaderboard_rows(label_blocks)
    overlap = label_overlap_stats(df)

    # BH-FDR correction applied ONCE, across the whole pre-specified primary
    # hypothesis family (every hypothesis x label x horizon row) — the
    # exploratory signal x dimension x horizon grid in `board` is intentionally
    # left uncorrected (see PRIMARY_HYPOTHESES docstring above).
    qvals = benjamini_hochberg([r["p_value"] for r in primary_hypothesis_raw], alpha=args.fdr_alpha)
    for row, q in zip(primary_hypothesis_raw, qvals):
        row["q_value"] = q["q_value"]
        row["reject_fdr"] = q["reject"]
    primary_hypothesis_report = primary_hypothesis_raw

    # Back-compat single-label top-level fields: prefer asof + the combined
    # T+7-T+63 horizon; fall back to the first available (label, horizon) block.
    primary_fam = PRIMARY_LABEL_FAMILY if PRIMARY_LABEL_FAMILY in label_blocks else next(iter(label_blocks))
    primary_horizons = label_blocks.get(primary_fam, {})
    primary_horizon = (
        PRIMARY_HORIZON_KEY if PRIMARY_HORIZON_KEY in primary_horizons else next(iter(primary_horizons), None)
    )
    primary = primary_horizons.get(primary_horizon, {}) if primary_horizon else {}
    if args.label:
        primary_label = args.label
    elif primary_fam == "event" and primary_horizon:
        primary_label = event_alpha_columns(primary_horizon)[0]
    elif primary_fam == "asof" and primary_horizon:
        primary_label = asof_alpha_columns(primary_horizon)[0]
    else:
        primary_label = args.label or EVENT_LABEL

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tickers": tickers,
        "labels_mode": args.labels if not args.label else "custom",
        "horizons": horizon_keys,
        "horizon_windows": {k: name for k, _a, _b, name in HORIZON_WINDOWS},
        "label": primary_label,
        "primary_label_key": primary_fam,
        "primary_horizon": primary_horizon,
        "label_entry": {
            "event": "company_t_plus_7 (model_date = earnings_date + 7d, weekend-rolled)",
            "asof": "investable_as_of_date (common cross-ticker T+7)",
        },
        "quarter_scope": list(quarters_filter) if quarters_filter else "full_history",
        "min_calendar_quarter": args.min_calendar_quarter,
        "call_date_only": not args.include_delayed,
        "investable_only_for_asof": args.investable_only,
        "recompute_cross_ticker_asof": not args.no_recompute_asof,
        "n_rows": int(len(df)),
        "n_rows_by_label": n_rows_by_label,
        "fiscal_periods": sorted(df["fiscal_period"].dropna().unique(), key=fiscal_period_sort_key),
        "label_overlap": overlap,
        "signals": primary,
        "by_label": label_blocks,
        "leaderboard": board,
        "divergence_hit_rate": divergence_by_label.get(f"{primary_fam}:{primary_horizon}", {}),
        "divergence_by_label": divergence_by_label,
        "jackknife": jackknife_rows,
        "agreement_effect": agreement_rows,
        "composite_enabled": args.composite,
        "composite_min_periods": args.composite_min_periods,
        "composite_weights": composite_weights_by_label,
        "cross_section_counts": cross_section_counts_by_label,
        "primary_hypotheses": [dict(h) for h in PRIMARY_HYPOTHESES],
        "primary_hypothesis_report": primary_hypothesis_report,
        "fdr_alpha": args.fdr_alpha,
        "dev_holdout": {
            "dev_cutoff": args.dev_cutoff,
            "holdout_start": args.holdout_start,
            "dev_only": args.dev_only,
            "holdout_only": args.holdout_only,
        },
    }

    ensure_cross_company_tree()
    json_path = cross_company_artifact("json", "narrative_signal_eval", "json", mkdir=True)
    csv_path = cross_company_artifact("csv", "narrative_signal_eval_period_ic", "csv", mkdir=True)
    board_path = cross_company_artifact("csv", "narrative_signal_eval_leaderboard", "csv", mkdir=True)
    jack_path = cross_company_artifact("csv", "narrative_signal_eval_jackknife", "csv", mkdir=True)
    agreement_path = cross_company_artifact("csv", "narrative_signal_eval_agreement", "csv", mkdir=True)
    primary_hyp_path = cross_company_artifact(
        "csv", "narrative_signal_eval_primary_hypotheses", "csv", mkdir=True
    )
    html_path = cross_company_artifact("reports", "narrative_signal_eval", "html", mkdir=True)

    period_concat = pd.concat(period_frames, ignore_index=True) if period_frames else pd.DataFrame()
    html_path.write_text(
        build_rank_ic_report_html(
            _json_safe(report),
            period_ics=_period_ic_payload(period_concat),
            company_period=_json_safe(company_period_rows),
        ),
        encoding="utf-8",
    )
    print(f"Wrote {html_path}")

    def _write_text(path: Path, text: str) -> None:
        try:
            path.write_text(text, encoding="utf-8")
            print(f"Wrote {path}")
        except OSError as exc:
            print(f"Warning: could not write {path}: {exc}", file=sys.stderr)

    def _write_csv(path: Path, frame: pd.DataFrame) -> None:
        try:
            frame.to_csv(path, index=False)
            print(f"Wrote {path}")
        except OSError as exc:
            print(f"Warning: could not write {path}: {exc}", file=sys.stderr)

    _write_text(json_path, json.dumps(_json_safe(report), indent=2))
    if not period_concat.empty:
        _write_csv(csv_path, period_concat)
    _write_csv(board_path, pd.DataFrame(board))
    if jackknife_rows:
        _write_csv(jack_path, pd.DataFrame(jackknife_rows))
    if agreement_rows:
        _write_csv(agreement_path, pd.DataFrame(agreement_rows))
    if primary_hypothesis_report:
        _write_csv(primary_hyp_path, pd.DataFrame(primary_hypothesis_report))
        n_reject = sum(1 for r in primary_hypothesis_report if r.get("reject_fdr"))
        print(
            f"\nPrimary hypotheses (FDR alpha={args.fdr_alpha}): "
            f"{n_reject}/{len(primary_hypothesis_report)} significant after correction."
        )
    if overlap:
        print(
            f"Legacy 0-90d event vs asof labels: differ={overlap.get('n_differ')} "
            f"equal={overlap.get('n_equal')} (of {overlap.get('n_both')})"
        )
    for fam, horizon_blocks in label_blocks.items():
        for hk, signals_block in horizon_blocks.items():
            print(f"\n[{fam}:{hk} — {horizon_display_name(hk)}] labeled_rows={n_rows_by_label.get(f'{fam}:{hk}')}")
            for signal, stats in signals_block.items():
                dm = stats.get("dimension_mean", {})
                print(
                    f"  {signal}: dimension-mean RankIC={dm.get('rank_ic_mean')} "
                    f"(n_dims={dm.get('n_dimensions')})"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
