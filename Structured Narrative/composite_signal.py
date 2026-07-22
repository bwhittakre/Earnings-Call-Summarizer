#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Walk-forward, point-in-time dimension-aware composite signal.

Blends the existing per-row narrative/quant signals into a single
``composite_score`` per ``(ticker, fiscal_period, dimension)`` row, using
weights fit *only* from periods strictly before the row being scored —
mirroring the expanding PIT z-score pattern already used for
``quant_z_pit`` (see ``narrative_zscore.py``'s ``MIN_HISTORY`` / ``_pit_z``).

Two things are computed per dimension, independently:

1. ``expanding_standardize`` — each input signal's own expanding, strictly-
   prior z-score (pooled across tickers), so signals on very different raw
   scales (a bounded LLM tone score, a boolean agreement flag, a z-score
   already) become comparable before being blended.
2. ``expanding_signal_weight`` — each input signal's *signed* expanding
   walk-forward RankIC-so-far for that dimension against the label being
   evaluated. A signal with a consistently positive history gets a positive
   weight; one with a consistently negative history gets a negative weight
   (used contrarian, sign-flipped, rather than dropped); one with no
   history yet (warm-up) or a wash gets a small/near-zero weight.

``build_composite_signal`` combines the two: for each row, the composite is
the weight-signed average of the standardized signals that have both a
value and a fitted weight for that row, renormalized by the sum of
|weight| so the composite's scale doesn't depend on how many signals
happen to contribute for a given (sparse) dimension.

Weighting is inherently specific to *which* forward-return label is being
predicted — see the horizon-reversal finding in the narrative-signal-eval
next-steps write-up (``change_magnitude`` flips from positive to negative
RankIC between the first and second three-week window). Callers must
therefore rebuild the composite fresh for each ``(label, horizon)`` pair
rather than reusing one composite across labels.

This module is eval-only: nothing here is persisted into
``feature_panel.csv`` or ``modeling_spine.csv``. See
``evaluate_narrative_signals.py`` for how it plugs into the per-
``(label, horizon)`` loop.
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd

from fiscal_period_util import fiscal_period_sort_key

# Excludes evidence_confidence (constant at 1.0 across the sampled spine —
# zero cross-sectional variance, a dead signal) and the delayed T+7
# guidance-revision z (out of scope for this pass; see build plan).
COMPOSITE_INPUT_SIGNALS: tuple[str, ...] = (
    "llm_level",
    "change_magnitude",
    "surprise_magnitude",
    "narrative_novelty",
    "quant_z_pit",
    "agrees_with_quant",
)

DEFAULT_MIN_PERIODS = 4


def _sorted_periods(df: pd.DataFrame, period_col: str) -> list[str]:
    values = df[period_col].dropna().astype(str).unique().tolist()
    if period_col == "fiscal_period":
        return sorted(values, key=fiscal_period_sort_key)
    return sorted(values)


def _spearman_ic(x: pd.Series, y: pd.Series) -> float | None:
    mask = x.notna() & y.notna()
    if mask.sum() < 3:
        return None
    xr = x[mask].rank(method="average")
    yr = y[mask].rank(method="average")
    corr = xr.corr(yr, method="pearson")
    if corr is None:
        return None
    v = float(corr)
    if np.isnan(v) or np.isinf(v):
        return None
    return v


def expanding_standardize(
    df: pd.DataFrame,
    signal_col: str,
    *,
    period_col: str,
    dimension_col: str = "dimension",
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> pd.Series:
    """Expanding, strictly-prior-period z-score of ``signal_col``.

    Computed independently per ``dimension_col`` value, pooling raw values
    across tickers within each period. A row at period ``p`` only ever uses
    rows from periods strictly before ``p`` (never rows sharing ``p``, and
    never later periods) to compute the mean/std it is scored against.
    NaN until ``min_periods`` distinct prior periods with data exist.
    """
    out = pd.Series(np.nan, index=df.index, dtype=float)
    if signal_col not in df.columns or dimension_col not in df.columns or period_col not in df.columns:
        return out

    for _dim, dim_df in df.groupby(dimension_col):
        periods = _sorted_periods(dim_df, period_col)
        if len(periods) <= min_periods:
            continue
        period_str = dim_df[period_col].astype(str)
        for i in range(min_periods, len(periods)):
            prior_periods = set(periods[:i])
            prior_vals = dim_df.loc[period_str.isin(prior_periods), signal_col].dropna().astype(float)
            if len(prior_vals) < 2:
                continue
            mu = float(prior_vals.mean())
            sd = float(prior_vals.std(ddof=0))
            if not sd or np.isnan(sd):
                continue
            mask = period_str == periods[i]
            idx = dim_df.index[mask]
            out.loc[idx] = (dim_df.loc[idx, signal_col].astype(float) - mu) / sd
    return out


def expanding_signal_weight(
    df: pd.DataFrame,
    signal_col: str,
    label_col: str,
    *,
    period_col: str,
    dimension_col: str = "dimension",
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> pd.Series:
    """Signed expanding walk-forward RankIC-so-far of ``signal_col`` vs
    ``label_col``, per ``dimension_col``, used as that signal's weight.

    The weight assigned to every row in period ``p`` is the mean of the
    per-period Spearman RankIC values computed for periods strictly before
    ``p`` (skipping periods where the RankIC wasn't computable, e.g. too few
    non-null pairs). NaN (→ zero contribution downstream) until at least
    ``min_periods`` prior periods have a computable RankIC.
    """
    out = pd.Series(np.nan, index=df.index, dtype=float)
    if (
        signal_col not in df.columns
        or label_col not in df.columns
        or dimension_col not in df.columns
    ):
        return out

    for _dim, dim_df in df.groupby(dimension_col):
        periods = _sorted_periods(dim_df, period_col)
        if len(periods) <= min_periods:
            continue
        period_str = dim_df[period_col].astype(str)
        period_ics: list[float | None] = []
        for p in periods:
            sub = dim_df[period_str == p]
            period_ics.append(_spearman_ic(sub[signal_col], sub[label_col]))
        for i in range(min_periods, len(periods)):
            prior = [v for v in period_ics[:i] if v is not None]
            if len(prior) < min_periods:
                continue
            weight = float(np.mean(prior))
            mask = period_str == periods[i]
            out.loc[dim_df.index[mask]] = weight
    return out


def build_composite_signal(
    df: pd.DataFrame,
    label_col: str,
    *,
    period_col: str,
    dimension_col: str = "dimension",
    input_signals: Iterable[str] = COMPOSITE_INPUT_SIGNALS,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> pd.Series:
    """Walk-forward, PIT-correct composite of ``input_signals`` for
    ``label_col``, fit independently per ``dimension_col`` value.

    For each row: ``sum(weight_s * standardized_s) / sum(|weight_s|)`` over
    the input signals ``s`` that have both a non-null standardized value and
    a fitted weight for that row. Renormalizing by the sum of absolute
    weights keeps the composite's scale stable even when a (sparse)
    dimension only has one or two applicable input signals. Never mutates
    ``df``; returns a new Series aligned to ``df.index``.
    """
    signals = [s for s in input_signals if s in df.columns]
    if not signals or label_col not in df.columns:
        return pd.Series(np.nan, index=df.index, dtype=float)

    standardized: dict[str, pd.Series] = {}
    weights: dict[str, pd.Series] = {}
    for s in signals:
        standardized[s] = expanding_standardize(
            df, s, period_col=period_col, dimension_col=dimension_col, min_periods=min_periods,
        )
        weights[s] = expanding_signal_weight(
            df, s, label_col, period_col=period_col, dimension_col=dimension_col, min_periods=min_periods,
        )

    numerator = pd.Series(0.0, index=df.index, dtype=float)
    denominator = pd.Series(0.0, index=df.index, dtype=float)
    any_contribution = pd.Series(False, index=df.index)
    for s in signals:
        contributes = standardized[s].notna() & weights[s].notna()
        w = weights[s].where(contributes, 0.0)
        z = standardized[s].where(contributes, 0.0)
        numerator = numerator + w * z
        denominator = denominator + w.abs()
        any_contribution = any_contribution | contributes

    composite = numerator / denominator.replace(0.0, np.nan)
    composite = composite.where(any_contribution, np.nan)
    return composite


def latest_composite_weights(
    df: pd.DataFrame,
    label_col: str,
    *,
    period_col: str,
    dimension_col: str = "dimension",
    input_signals: Iterable[str] = COMPOSITE_INPUT_SIGNALS,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> dict[str, dict[str, float]]:
    """``{dimension: {signal: weight}}`` using the most recent period's
    expanding weight for each ``(dimension, signal)`` pair.

    A diagnostic for interpretability (what is the composite actually doing
    right now, for each dimension) — not used in the composite computation
    itself. Signals with no usable weight yet at the latest period are
    omitted from that dimension's dict; dimensions with no usable signals at
    all are omitted entirely.
    """
    signals = [s for s in input_signals if s in df.columns]
    out: dict[str, dict[str, float]] = {}
    if not signals or label_col not in df.columns or dimension_col not in df.columns:
        return out

    for dim, dim_df in df.groupby(dimension_col):
        dim = str(dim)
        periods = _sorted_periods(dim_df, period_col)
        if len(periods) <= min_periods:
            continue
        latest_period = periods[-1]
        latest_mask = dim_df[period_col].astype(str) == latest_period
        latest_idx = dim_df.index[latest_mask]

        dim_weights: dict[str, float] = {}
        for s in signals:
            w = expanding_signal_weight(
                dim_df, s, label_col, period_col=period_col, dimension_col=dimension_col, min_periods=min_periods,
            )
            vals = w.loc[latest_idx].dropna()
            if not vals.empty:
                dim_weights[s] = round(float(vals.iloc[0]), 4)
        if dim_weights:
            out[dim] = dim_weights
    return out
