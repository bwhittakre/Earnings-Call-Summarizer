#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward IC / RankIC evaluation for narrative modeling spine signals.

Labels (alpha_spec_0_90*) are forward returns from t+7 entry (model_date) — never model inputs.
Call-date signals use call_feature_available_date; T+7 revision z uses t7_feature_available_date
and is only paired with labels that start on/after that date (default alpha already does).
Delayed features (quant_guidance_revision_z_pit) are excluded from call-date eval by default.

    python "Structured Narrative/evaluate_narrative_signals.py"
    python "Structured Narrative/evaluate_narrative_signals.py" --tickers MSFT NVDA --include-delayed
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from company_config import PILOT_OUTPUT_QUARTERS, PILOT_TICKERS  # noqa: E402
from export_modeling_spine import LABEL_COLUMNS, filter_registry_complete, load_panel  # noqa: E402
from fiscal_period_util import fiscal_period_sort_key  # noqa: E402
from output_paths import cross_company_artifact, ensure_cross_company_tree  # noqa: E402
from spine_export import CONSOLIDATED_SPINE_COLUMNS, panel_to_spine  # noqa: E402

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

DEFAULT_LABEL = "alpha_spec_0_90"

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


def _pearson_ic(x: pd.Series, y: pd.Series) -> float | None:
    mask = x.notna() & y.notna()
    if mask.sum() < 3:
        return None
    return float(x[mask].corr(y[mask], method="pearson"))


def _spearman_ic(x: pd.Series, y: pd.Series) -> float | None:
    mask = x.notna() & y.notna()
    if mask.sum() < 3:
        return None
    xr = x[mask].rank(method="average")
    yr = y[mask].rank(method="average")
    return float(xr.corr(yr, method="pearson"))


def walk_forward_period_ics(
    df: pd.DataFrame,
    signal: str,
    label: str,
) -> pd.DataFrame:
    rows: list[dict] = []
    periods = sorted(df["fiscal_period"].unique(), key=fiscal_period_sort_key)
    for fp in periods:
        sub = df[df["fiscal_period"] == fp]
        ic = _pearson_ic(sub[signal], sub[label])
        rank_ic = _spearman_ic(sub[signal], sub[label])
        if ic is None and rank_ic is None:
            continue
        rows.append(
            {
                "fiscal_period": fp,
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
        return {"n_periods": 0}
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
    return out


def dimension_ics(df: pd.DataFrame, signal: str, label: str) -> pd.DataFrame:
    rows: list[dict] = []
    for dim, sub in df.groupby("dimension"):
        ic = _pearson_ic(sub[signal], sub[label])
        rank_ic = _spearman_ic(sub[signal], sub[label])
        rows.append(
            {
                "dimension": dim,
                "signal": signal,
                "n": int(sub[[signal, label]].dropna().shape[0]),
                "ic": ic,
                "rank_ic": rank_ic,
            }
        )
    return pd.DataFrame(rows)


def divergence_hit_rate(df: pd.DataFrame, label: str) -> dict:
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


DELAYED_SIGNALS = {"quant_guidance_revision_z_pit"}


def load_eval_frame(tickers: list[str], *, call_date_only: bool = True) -> pd.DataFrame:
    quarter_set = set(PILOT_OUTPUT_QUARTERS)
    frames: list[pd.DataFrame] = []
    for ticker in tickers:
        panel = load_panel(ticker)
        panel = filter_registry_complete(panel, ticker)
        panel = panel[panel["fiscal_period"].isin(quarter_set)].copy()
        spine = panel_to_spine(panel)
        for c in LABEL_COLUMNS:
            if c in panel.columns:
                spine[c] = panel[c].values
        frames.append(spine)
    if not frames:
        raise FileNotFoundError("No feature panels loaded.")
    stacked = pd.concat(frames, ignore_index=True)
    stacked = stacked.sort_values(["ticker", "fiscal_period", "dimension"]).reset_index(drop=True)
    if call_date_only:
        # Call-date features: available at earnings/as_of (feature_availability_date == call date).
        call_col = (
            "call_feature_available_date"
            if "call_feature_available_date" in stacked.columns
            else "feature_availability_date"
        )
        stacked = stacked[stacked[call_col].astype(str).str[:10] == stacked["earnings_date"].astype(str).str[:10]].copy()
    return stacked


def _signal_eval_frame(df: pd.DataFrame, signal: str) -> pd.DataFrame:
    """Restrict delayed revision signals to rows with T+7 availability (label is t+7 entry)."""
    if signal not in DELAYED_SIGNALS:
        return df
    out = df[df[signal].notna()].copy()
    if "t7_feature_available_date" in out.columns:
        out = out[out["t7_feature_available_date"].notna()].copy()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Walk-forward IC/RankIC for narrative signals.")
    ap.add_argument("--tickers", nargs="+", default=list(PILOT_TICKERS))
    ap.add_argument("--label", default=DEFAULT_LABEL)
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
    args = ap.parse_args()
    tickers = [t.upper() for t in args.tickers]
    label = args.label
    signals = args.signals or list(SIGNAL_COLUMNS)
    if not args.include_delayed:
        signals = [s for s in signals if s in CALL_DATE_SIGNALS]

    try:
        # Always load full panel for delayed path; call-date path filters to call availability.
        df = load_eval_frame(tickers, call_date_only=not args.include_delayed)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if label not in df.columns or df[label].notna().sum() == 0:
        print(f"Error: label column {label!r} missing or empty.", file=sys.stderr)
        return 1

    eval_df = df[df[label].notna()].copy()
    signal_summary: dict[str, dict] = {}
    period_frames: list[pd.DataFrame] = []

    for signal in signals:
        if signal not in eval_df.columns:
            continue
        sig_df = _signal_eval_frame(eval_df, signal)
        if sig_df.empty:
            continue
        period_ics = walk_forward_period_ics(sig_df, signal, label)
        period_frames.append(period_ics)
        signal_summary[signal] = {
            "walk_forward": summarize_ics(period_ics),
            "pooled_ic": _pearson_ic(sig_df[signal], sig_df[label]),
            "pooled_rank_ic": _spearman_ic(sig_df[signal], sig_df[label]),
            "by_dimension": dimension_ics(sig_df, signal, label).to_dict(orient="records"),
            "quintile_spread": quintile_spread(sig_df, signal, label),
            "n_rows": int(len(sig_df)),
            "availability": (
                "t7_feature_available_date"
                if signal in DELAYED_SIGNALS
                else "call_feature_available_date"
            ),
            "label_entry": "t_plus_7",
        }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tickers": tickers,
        "label": label,
        "label_entry": "t_plus_7",
        "quarter_scope": list(PILOT_OUTPUT_QUARTERS),
        "call_date_only": not args.include_delayed,
        "n_rows": int(len(eval_df)),
        "fiscal_periods": sorted(eval_df["fiscal_period"].unique(), key=fiscal_period_sort_key),
        "signals": signal_summary,
        "divergence_hit_rate": divergence_hit_rate(eval_df, label),
    }

    ensure_cross_company_tree()
    json_path = cross_company_artifact("json", "narrative_signal_eval", "json", mkdir=True)
    csv_path = cross_company_artifact("csv", "narrative_signal_eval_period_ic", "csv", mkdir=True)
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if period_frames:
        pd.concat(period_frames, ignore_index=True).to_csv(csv_path, index=False)

    print(f"Wrote {json_path}")
    print(f"Evaluated {len(eval_df)} labeled rows across {len(tickers)} ticker(s)")
    for signal, stats in signal_summary.items():
        wf = stats.get("walk_forward", {})
        print(
            f"  {signal}: RankIC mean={wf.get('rank_ic_mean')} "
            f"(n_periods={wf.get('n_periods')}) "
            f"pooled RankIC={stats.get('pooled_rank_ic')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
