#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Walk-forward IC / RankIC evaluation for narrative modeling spine signals.

Labels (alpha_spec_0_90* / alpha_spec_asof_0_90*) are forward returns — never model inputs.
Call-date signals use call_feature_available_date; T+7 revision z uses t7_feature_available_date
and is only paired with labels that start on/after that date.

Cross-ticker investable as-of is recomputed on the stacked eval frame (per-ticker panels
alone set investable_as_of to each name's own T+7). As-of alphas are then rebuilt from
cached specific returns.

    python "Structured Narrative/evaluate_narrative_signals.py"
    python "Structured Narrative/evaluate_narrative_signals.py" --labels both
    python "Structured Narrative/evaluate_narrative_signals.py" --tickers MSFT NVDA --include-delayed
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
    apply_asof_alpha_labels,
)
from company_config import PILOT_OUTPUT_QUARTERS, PILOT_TICKERS  # noqa: E402
from export_modeling_spine import filter_registry_complete, load_panel  # noqa: E402
from fiscal_period_util import fiscal_period_sort_key  # noqa: E402
from output_paths import cross_company_artifact, ensure_cross_company_tree  # noqa: E402
from period_dates import (  # noqa: E402
    apply_feature_availability_dates,
    apply_investable_cross_section_columns,
    enrich_panel_period_columns,
)
from spine_export import panel_to_spine, standardize_surprise_novelty_exclusivity  # noqa: E402

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

DEFAULT_LABEL = "alpha_spec_0_90"
EVENT_LABEL = "alpha_spec_0_90"
ASOF_LABEL = "alpha_spec_asof_0_90"

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
) -> pd.DataFrame:
    rows: list[dict] = []
    if period_col not in df.columns:
        return pd.DataFrame(rows)
    if period_col == "fiscal_period":
        periods = sorted(df[period_col].dropna().unique(), key=fiscal_period_sort_key)
    else:
        periods = sorted(df[period_col].dropna().astype(str).unique())
    for fp in periods:
        sub = df[df[period_col].astype(str) == str(fp)]
        ic = _pearson_ic(sub[signal], sub[label])
        rank_ic = _spearman_ic(sub[signal], sub[label])
        if ic is None and rank_ic is None:
            continue
        rows.append(
            {
                "fiscal_period": str(fp),
                "period_col": period_col,
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


def load_eval_frame(
    tickers: list[str],
    *,
    call_date_only: bool = True,
    quarters: list[str] | None = None,
    recompute_cross_ticker_asof: bool = True,
    fetch_returns_if_missing: bool = True,
) -> pd.DataFrame:
    """Stack panels and rebuild cross-ticker investable as-of + asof alphas."""
    quarter_set = set(quarters or PILOT_OUTPUT_QUARTERS)
    frames: list[pd.DataFrame] = []
    for ticker in tickers:
        panel = load_panel(ticker)
        panel = filter_registry_complete(panel, ticker)
        panel = panel[panel["fiscal_period"].isin(quarter_set)].copy()
        panel = standardize_surprise_novelty_exclusivity(panel)
        panel = enrich_panel_period_columns(panel)
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
            "model_date",
        ):
            if c in panel.columns and c not in spine.columns:
                spine[c] = panel[c].values
        frames.append(spine)
    if not frames:
        raise FileNotFoundError("No feature panels loaded.")
    stacked = pd.concat(frames, ignore_index=True)
    stacked = stacked.sort_values(["ticker", "fiscal_period", "dimension"]).reset_index(drop=True)

    if recompute_cross_ticker_asof:
        # Drop per-ticker investable columns before cross-ticker rebuild.
        for c in ("investable_as_of_date", "days_since_earnings", "feature_age_days", "investable_ready"):
            if c in stacked.columns:
                stacked = stacked.drop(columns=[c])
        stacked = apply_investable_cross_section_columns(stacked)
        stacked = apply_asof_alpha_labels(stacked, fetch_if_missing=fetch_returns_if_missing)

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
    """Return per-signal stats and concatenated period-IC rows."""
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
        wf = summarize_ics(period_ics)
        signal_summary[signal] = {
            "walk_forward": wf,
            "pooled_ic": _pearson_ic(sig_df[signal], sig_df[label]),
            "pooled_rank_ic": _spearman_ic(sig_df[signal], sig_df[label]),
            "by_dimension": dimension_ics(sig_df, signal, label).to_dict(orient="records"),
            "quintile_spread": quintile_spread(sig_df, signal, label),
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
    """Jackknife: WF RankIC mean with each ticker held out."""
    tickers = sorted(df["ticker"].dropna().astype(str).str.upper().unique())
    rows: list[dict] = []
    for held in tickers:
        sub = df[df["ticker"].astype(str).str.upper() != held]
        summary, _ = evaluate_signals(
            sub, signals, label, period_col=period_col, universe=universe
        )
        for signal, stats in summary.items():
            wf = stats.get("walk_forward", {})
            rows.append(
                {
                    "held_out_ticker": held,
                    "signal": signal,
                    "label": label,
                    "universe": universe,
                    "rank_ic_mean": wf.get("rank_ic_mean"),
                    "rank_ic_ir": wf.get("rank_ic_ir"),
                    "pooled_rank_ic": _finite(stats.get("pooled_rank_ic")),
                    "n_periods": wf.get("n_periods"),
                    "n_rows": stats.get("n_rows"),
                }
            )
    return rows


def leaderboard_rows(label_blocks: dict[str, dict[str, dict]]) -> list[dict]:
    """Flatten signal × label summaries into leaderboard rows."""
    rows: list[dict] = []
    for label_key, signals in label_blocks.items():
        for signal, stats in signals.items():
            wf = stats.get("walk_forward", {})
            rows.append(
                {
                    "signal": signal,
                    "label": label_key,
                    "universe": stats.get("universe"),
                    "rank_ic_mean": wf.get("rank_ic_mean"),
                    "rank_ic_ir": wf.get("rank_ic_ir"),
                    "pooled_rank_ic": _finite(stats.get("pooled_rank_ic")),
                    "positive_rank_ic_hit_rate": wf.get("positive_rank_ic_hit_rate"),
                    "n_periods": wf.get("n_periods"),
                    "n_rows": stats.get("n_rows"),
                }
            )
    rows.sort(
        key=lambda r: (
            -(r["rank_ic_mean"] if r["rank_ic_mean"] is not None else -999),
            r["signal"],
            r["label"],
        )
    )
    return rows


def label_overlap_stats(df: pd.DataFrame) -> dict:
    """How often event vs asof alphas differ after cross-ticker rebuild."""
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
        help="Single label column (legacy). Prefer --labels.",
    )
    ap.add_argument(
        "--labels",
        choices=("event", "asof", "both"),
        default="both",
        help="Which forward-label set(s) to evaluate (default: both).",
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
        default=list(PILOT_OUTPUT_QUARTERS),
        help="Fiscal periods to include (default: PILOT_OUTPUT_QUARTERS).",
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
        "--no-recompute-asof",
        action="store_true",
        help="Skip cross-ticker investable rebuild / asof alpha recompute.",
    )
    args = ap.parse_args()
    tickers = [t.upper() for t in args.tickers]
    signals = args.signals or list(SIGNAL_COLUMNS)
    if not args.include_delayed:
        signals = [s for s in signals if s in CALL_DATE_SIGNALS]

    # Legacy --label overrides --labels to a single column.
    if args.label:
        label_specs = [("custom", args.label, "all", "fiscal_period")]
    elif args.labels == "event":
        label_specs = [("event", EVENT_LABEL, "all", "fiscal_period")]
    elif args.labels == "asof":
        univ = "investable_ready" if args.investable_only else "all"
        label_specs = [("asof", ASOF_LABEL, univ, "period_end_calendar_quarter")]
    else:
        label_specs = [
            ("event", EVENT_LABEL, "all", "fiscal_period"),
            (
                "asof",
                ASOF_LABEL,
                "investable_ready" if args.investable_only else "all",
                "period_end_calendar_quarter",
            ),
        ]

    try:
        df = load_eval_frame(
            tickers,
            call_date_only=not args.include_delayed,
            quarters=args.quarters,
            recompute_cross_ticker_asof=not args.no_recompute_asof,
        )
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    label_blocks: dict[str, dict[str, dict]] = {}
    period_frames: list[pd.DataFrame] = []
    jackknife_rows: list[dict] = []
    divergence_by_label: dict[str, dict] = {}
    n_rows_by_label: dict[str, int] = {}

    for key, label, universe, period_col in label_specs:
        if label not in df.columns or df[label].notna().sum() == 0:
            print(f"Warning: label {label!r} missing or empty — skipping.", file=sys.stderr)
            continue
        work = df
        if universe == "investable_ready":
            if "investable_ready" not in work.columns:
                print("Warning: investable_ready missing — using all rows for as-of.", file=sys.stderr)
            else:
                work = work[work["investable_ready"] == True].copy()  # noqa: E712
        # Prefer calendar-quarter WF for as-of when column present; else fiscal.
        pcol = period_col if period_col in work.columns else "fiscal_period"
        summary, period_df = evaluate_signals(
            work, signals, label, period_col=pcol, universe=universe
        )
        label_blocks[key] = summary
        n_rows_by_label[key] = int(work[label].notna().sum())
        divergence_by_label[key] = divergence_hit_rate(work, label)
        if not period_df.empty:
            period_frames.append(period_df)
        if args.jackknife and len(tickers) > 1:
            jackknife_rows.extend(
                leave_one_ticker_out(
                    work, signals, label, period_col=pcol, universe=universe
                )
            )

    if not label_blocks:
        print("Error: no labels evaluated.", file=sys.stderr)
        return 1

    board = leaderboard_rows(label_blocks)
    overlap = label_overlap_stats(df)

    # Back-compat single-label top-level fields (first / only block).
    primary_key = next(iter(label_blocks))
    primary = label_blocks[primary_key]
    primary_label = label_specs[0][1] if args.label else (
        EVENT_LABEL if primary_key == "event" else ASOF_LABEL if primary_key == "asof" else args.label
    )
    if args.label:
        primary_label = args.label
    elif primary_key == "event":
        primary_label = EVENT_LABEL
    elif primary_key == "asof":
        primary_label = ASOF_LABEL
    else:
        primary_label = EVENT_LABEL

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tickers": tickers,
        "labels_mode": args.labels if not args.label else "custom",
        "label": primary_label,
        "label_entry": {
            "event": "company_t_plus_7",
            "asof": "investable_as_of_date",
        },
        "quarter_scope": list(args.quarters),
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
        "divergence_hit_rate": divergence_by_label.get(primary_key, {}),
        "divergence_by_label": divergence_by_label,
        "jackknife": jackknife_rows,
    }

    ensure_cross_company_tree()
    json_path = cross_company_artifact("json", "narrative_signal_eval", "json", mkdir=True)
    csv_path = cross_company_artifact("csv", "narrative_signal_eval_period_ic", "csv", mkdir=True)
    board_path = cross_company_artifact("csv", "narrative_signal_eval_leaderboard", "csv", mkdir=True)
    jack_path = cross_company_artifact("csv", "narrative_signal_eval_jackknife", "csv", mkdir=True)

    json_path.write_text(json.dumps(_json_safe(report), indent=2), encoding="utf-8")
    if period_frames:
        pd.concat(period_frames, ignore_index=True).to_csv(csv_path, index=False)
    pd.DataFrame(board).to_csv(board_path, index=False)
    if jackknife_rows:
        pd.DataFrame(jackknife_rows).to_csv(jack_path, index=False)

    print(f"Wrote {json_path}")
    print(f"Wrote {board_path}")
    if jackknife_rows:
        print(f"Wrote {jack_path}")
    if overlap:
        print(
            f"Event vs asof labels: differ={overlap.get('n_differ')} "
            f"equal={overlap.get('n_equal')} (of {overlap.get('n_both')})"
        )
    for key, signals_block in label_blocks.items():
        print(f"\n[{key}] labeled_rows={n_rows_by_label.get(key)}")
        for signal, stats in signals_block.items():
            wf = stats.get("walk_forward", {})
            print(
                f"  {signal}: RankIC mean={wf.get('rank_ic_mean')} "
                f"IR={wf.get('rank_ic_ir')} "
                f"hit={wf.get('positive_rank_ic_hit_rate')} "
                f"pooled={_finite(stats.get('pooled_rank_ic'))}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
