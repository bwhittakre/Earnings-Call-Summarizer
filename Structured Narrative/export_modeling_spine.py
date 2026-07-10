#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Export a cross-company modeling spine from per-ticker feature panels.

    python "Structured Narrative/export_modeling_spine.py"
    python "Structured Narrative/export_modeling_spine.py" --tickers AMZN --include-labels
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

from company_config import PILOT_TICKERS  # noqa: E402
from output_paths import cross_company_artifact, ensure_cross_company_tree, resolve_read  # noqa: E402
from quarter_registry import is_quarter_complete, load_registry  # noqa: E402

DEFAULT_COLUMNS = [
    "ticker",
    "fiscal_period",
    "dimension",
    "as_of_date",
    "earnings_date",
    "quant_z",
    "llm_level",
    "change_magnitude",
    "surprise_magnitude",
    "agrees_with_quant",
    "narrative_quant_gap",
    "is_divergence",
    "signal_stack",
]

LABEL_COLUMNS = [
    "alpha_spec_0_90",
    "alpha_spec_0_90_z",
    "alpha_spec_0_90_complete",
]


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
    args = ap.parse_args()
    tickers = [t.upper() for t in args.tickers]
    cols = DEFAULT_COLUMNS + (LABEL_COLUMNS if args.include_labels else [])

    frames: list[pd.DataFrame] = []
    for ticker in tickers:
        panel = load_panel(ticker)
        panel = filter_registry_complete(panel, ticker)
        missing = [c for c in cols if c not in panel.columns]
        for c in missing:
            panel[c] = None
        frames.append(panel[cols])

    if not frames:
        print("No panels loaded.", file=sys.stderr)
        return 1

    stacked = pd.concat(frames, ignore_index=True)
    stacked = stacked.sort_values(["ticker", "fiscal_period", "dimension"]).reset_index(drop=True)

    ensure_cross_company_tree()
    csv_path = cross_company_artifact("csv", "modeling_spine", "csv", mkdir=True)
    pq_path = cross_company_artifact("parquet", "modeling_spine", "parquet", mkdir=True)
    summary_path = cross_company_artifact("json", "modeling_spine_summary", "json", mkdir=True)

    stacked.to_csv(csv_path, index=False)
    try:
        stacked.to_parquet(pq_path, index=False)
    except Exception as exc:
        print(f"  ! parquet write skipped: {exc}")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tickers": tickers,
        "row_count": int(len(stacked)),
        "fiscal_periods": sorted(stacked["fiscal_period"].unique().tolist()),
        "columns": cols,
        "include_labels": args.include_labels,
    }
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {csv_path} ({len(stacked)} rows)")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
