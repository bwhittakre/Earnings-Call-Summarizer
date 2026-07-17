#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export a cross-company modeling spine from per-ticker feature panels.

    python "Structured Narrative/export_modeling_spine.py"
    python "Structured Narrative/export_modeling_spine.py" --tickers AMZN --include-labels
    python "Structured Narrative/export_modeling_spine.py" --include-labels --labels asof
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from asof_alpha import apply_asof_alpha_labels, label_column_sets  # noqa: E402
from company_config import PILOT_OUTPUT_QUARTERS, PILOT_TICKERS  # noqa: E402
from coverage import annotate_included  # noqa: E402
from output_paths import cross_company_artifact, ensure_cross_company_tree, resolve_read  # noqa: E402
from period_dates import (  # noqa: E402
    apply_feature_availability_dates,
    apply_investable_cross_section_columns,
    enrich_panel_period_columns,
)
from quarter_registry import is_quarter_complete, load_registry  # noqa: E402
from spine_export import (  # noqa: E402
    CONSOLIDATED_SPINE_COLUMNS,
    panel_to_spine,
    standardize_surprise_novelty_exclusivity,
)
from dimension_order import sort_panel_by_dimension  # noqa: E402

DEFAULT_COLUMNS = list(CONSOLIDATED_SPINE_COLUMNS)

# Back-compat alias for evaluate_narrative_signals
LABEL_COLUMNS = label_column_sets("event")


def load_panel(ticker: str) -> pd.DataFrame:
    path = resolve_read(ticker, "feature_panel", "csv", layer="csv")
    if path is None:
        raise FileNotFoundError(
            f"Missing csv/feature_panel.csv for {ticker}. "
            f"Run build_feature_panel.py --ticker {ticker}."
        )
    return pd.read_csv(path)


def filter_registry_complete(panel: pd.DataFrame, ticker: str) -> pd.DataFrame:
    reg = load_registry(ticker)
    prior_only = set(reg.get("prior_only_quarters", []))
    fps = [
        fp
        for fp, _ in reg.get("scored_quarters", {}).items()
        if is_quarter_complete(reg, fp) and fp not in prior_only
    ]
    if not fps:
        return panel
    return panel[panel["fiscal_period"].isin(fps)].copy()


def main() -> int:
    ap = argparse.ArgumentParser(description="Export cross-company modeling spine.")
    ap.add_argument("--tickers", nargs="+", default=list(PILOT_TICKERS))
    ap.add_argument(
        "--include-labels",
        action="store_true",
        help="Include forward alpha label columns (research only; not for live inference).",
    )
    ap.add_argument(
        "--labels",
        choices=("event", "asof", "both"),
        default="both",
        help="Which research label set to include with --include-labels (default: both).",
    )
    ap.add_argument(
        "--quarters",
        nargs="+",
        default=list(PILOT_OUTPUT_QUARTERS),
        help="Restrict to these fiscal periods (default: 8-quarter pilot scope).",
    )
    args = ap.parse_args()
    tickers = [t.upper() for t in args.tickers]
    quarter_set = set(args.quarters)
    label_cols = label_column_sets(args.labels) if args.include_labels else []

    frames: list[pd.DataFrame] = []
    for ticker in tickers:
        panel = load_panel(ticker)
        panel = filter_registry_complete(panel, ticker)
        panel = panel[panel["fiscal_period"].isin(quarter_set)].copy()
        frames.append(panel)

    if not frames:
        print("No panels loaded.", file=sys.stderr)
        return 1

    stacked = pd.concat(frames, ignore_index=True)
    stacked = standardize_surprise_novelty_exclusivity(stacked)
    stacked = enrich_panel_period_columns(stacked)
    if "call_feature_available_date" not in stacked.columns:
        stacked = apply_feature_availability_dates(stacked)
    stacked = apply_investable_cross_section_columns(stacked)
    stacked = annotate_included(stacked)
    if args.include_labels and any(c.startswith("alpha_spec_asof") for c in label_cols):
        stacked = apply_asof_alpha_labels(stacked, fetch_if_missing=True)

    spine = panel_to_spine(stacked)
    for c in label_cols:
        if c in stacked.columns:
            spine[c] = stacked[c].values
        else:
            spine[c] = None

    spine = sort_panel_by_dimension(
        spine,
        leading_columns=("ticker", "fiscal_period", "period_end_date"),
    )
    out_cols = DEFAULT_COLUMNS + [c for c in label_cols if c not in DEFAULT_COLUMNS]

    ensure_cross_company_tree()
    stem = "modeling_spine"
    if args.include_labels and args.labels == "event":
        stem = "modeling_spine_event"
    elif args.include_labels and args.labels == "asof":
        stem = "modeling_spine_asof"
    elif args.include_labels and args.labels == "both":
        stem = "modeling_spine"

    csv_path = cross_company_artifact("csv", stem, "csv", mkdir=True)
    pq_path = cross_company_artifact("parquet", stem, "parquet", mkdir=True)
    summary_path = cross_company_artifact("json", f"{stem}_summary", "json", mkdir=True)

    spine[out_cols].to_csv(csv_path, index=False)
    try:
        spine[out_cols].to_parquet(pq_path, index=False)
    except Exception as exc:
        print(f"  ! parquet write skipped: {exc}")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tickers": tickers,
        "quarter_scope": sorted(quarter_set),
        "row_count": int(len(spine)),
        "fiscal_periods": sorted(spine["fiscal_period"].unique().tolist()),
        "columns": out_cols,
        "include_labels": args.include_labels,
        "labels_mode": args.labels if args.include_labels else None,
        "label_sets": {
            "event": "alpha_spec_0_90* from each company T+7 / model_date",
            "asof": "alpha_spec_asof_0_90* from investable_as_of_date",
        },
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {csv_path} ({len(spine)} rows)")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
