#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward IC / RankIC evaluation for narrative modeling spine signals.

Labels (alpha_spec_0_90*) are forward returns — never used as model inputs.

    python "Structured Narrative/evaluate_narrative_signals.py"
    python "Structured Narrative/evaluate_narrative_signals.py" --tickers MSFT NVDA --include-labels
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

from company_config import PILOT_TICKERS  # noqa: E402
from export_modeling_spine import (  # noqa: E402
    DEFAULT_COLUMNS,
    LABEL_COLUMNS,
    filter_registry_complete,
    load_panel,
)
from fiscal_period_util import fiscal_period_sort_key  # noqa: E402
from output_paths import cross_company_artifact, ensure_cross_company_tree  # noqa: E402

SIGNAL_COLUMNS = [
    "llm_level",
    "change_magnitude",
    "quant_z_delta",
    "surprise_magnitude",
    "narrative_quant_gap",
    "abs_narrative_quant_gap",
    "surprise_quant_interaction",
    "llm_level_4q_mean",
    "change_magnitude_4q_mean",
]

DEFAULT_LABEL = "alpha_spec_0_90"


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
    """Cross-sectional IC per fiscal period (pool tickers × dimensions at T)."""
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
    """Mean label when surprise diverges vs agrees (quant-comparable rows only)."""
    sub = df[df["is_divergence"].notna() & df[label].notna()].copy()
    if sub.empty:
        return {"n": 0}
    div = sub[sub["is_divergence"] == True]  # noqa: E712
    agree = sub[sub["is_divergence"] == False]  # noqa: E712
    return {
        "n_total": int(len(sub)),
        "n_divergence": int(len(div)),
        "n_agree": int(len(agree)),
        "mean_label_divergence": round(float(div[label].mean()), 6) if len(div) else None,
        "mean_label_agree": round(float(agree[label].mean()), 6) if len(agree) else None,
        "hit_rate_divergence_positive": (
            round(float((div[label] > 0).mean()), 4) if len(div) else None
        ),
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


def load_eval_frame(tickers: list[str], include_labels: bool) -> pd.DataFrame:
    cols = DEFAULT_COLUMNS + (LABEL_COLUMNS if include_labels else [])
    frames: list[pd.DataFrame] = []
    for ticker in tickers:
        panel = load_panel(ticker)
        panel = filter_registry_complete(panel, ticker)
        for c in cols:
            if c not in panel.columns:
                panel[c] = None
        frames.append(panel[cols])
    if not frames:
        raise FileNotFoundError("No feature panels loaded.")
    stacked = pd.concat(frames, ignore_index=True)
    return stacked.sort_values(["ticker", "fiscal_period", "dimension"]).reset_index(drop=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Walk-forward IC/RankIC for narrative signals.")
    ap.add_argument("--tickers", nargs="+", default=list(PILOT_TICKERS))
    ap.add_argument("--include-labels", action="store_true", default=True)
    ap.add_argument("--label", default=DEFAULT_LABEL)
    ap.add_argument(
        "--signals",
        nargs="+",
        default=SIGNAL_COLUMNS,
        help="Panel columns to evaluate as signals.",
    )
    args = ap.parse_args()
    tickers = [t.upper() for t in args.tickers]
    label = args.label

    try:
        df = load_eval_frame(tickers, include_labels=True)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if label not in df.columns or df[label].notna().sum() == 0:
        print(
            f"Error: label column {label!r} missing or empty. "
            "Ensure dimension_scores spine includes alpha labels.",
            file=sys.stderr,
        )
        return 1

    eval_df = df[df[label].notna()].copy()
    signal_summary: dict[str, dict] = {}
    period_frames: list[pd.DataFrame] = []

    for signal in args.signals:
        if signal not in eval_df.columns:
            continue
        period_ics = walk_forward_period_ics(eval_df, signal, label)
        period_frames.append(period_ics)
        signal_summary[signal] = {
            "walk_forward": summarize_ics(period_ics),
            "pooled_ic": _pearson_ic(eval_df[signal], eval_df[label]),
            "pooled_rank_ic": _spearman_ic(eval_df[signal], eval_df[label]),
            "by_dimension": dimension_ics(eval_df, signal, label).to_dict(orient="records"),
            "quintile_spread": quintile_spread(eval_df, signal, label),
        }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tickers": tickers,
        "label": label,
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
    div = report["divergence_hit_rate"]
    print(
        f"  divergence hit rate: n={div.get('n_divergence')} "
        f"mean_label={div.get('mean_label_divergence')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
