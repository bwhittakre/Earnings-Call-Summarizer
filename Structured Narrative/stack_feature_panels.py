#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stack per-ticker feature panels into one cross-company dataset.

    python "Structured Narrative/stack_feature_panels.py"
    python "Structured Narrative/stack_feature_panels.py" --tickers AMZN MSFT NVDA
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from company_config import FY2025_OUTPUT_QUARTERS, PILOT_TICKERS  # noqa: E402


def load_panel(ticker: str) -> pd.DataFrame:
    path = OUT_DIR / f"{ticker}_feature_panel.csv"
    if not path.exists():
        raise FileNotFoundError(f"Missing {path.name}. Run build_feature_panel.py --ticker {ticker}.")
    return pd.read_csv(path)


def build_summary(panel: pd.DataFrame, tickers: list[str]) -> dict:
    output_mask = panel["fiscal_period"].isin(FY2025_OUTPUT_QUARTERS)
    out = panel[output_mask]
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tickers": tickers,
        "output_quarters": list(FY2025_OUTPUT_QUARTERS),
        "total_rows": int(len(panel)),
        "output_scope_rows": int(len(out)),
        "by_ticker": {},
    }
    for ticker in tickers:
        sub = out[out["ticker"] == ticker]
        summary["by_ticker"][ticker] = {
            "rows": int(len(sub)),
            "quarters": sorted(sub["fiscal_period"].unique().tolist()),
            "has_level_pct": round(float(sub["has_level"].mean() * 100), 1) if len(sub) else 0.0,
            "has_delta_pct": round(float(sub["has_delta"].mean() * 100), 1) if len(sub) else 0.0,
            "has_surprise_pct": round(float(sub["has_surprise"].mean() * 100), 1) if len(sub) else 0.0,
            "divergence_count": int(sub["is_divergence"].fillna(False).sum()) if "is_divergence" in sub else 0,
        }
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description="Stack feature panels across tickers.")
    ap.add_argument("--tickers", nargs="+", default=list(PILOT_TICKERS), help="Tickers to stack.")
    ap.add_argument(
        "--output-prefix",
        default="cross_company_FY2025",
        help="Output file prefix under output/.",
    )
    args = ap.parse_args()
    tickers = [t.upper() for t in args.tickers]

    frames = []
    for ticker in tickers:
        df = load_panel(ticker)
        frames.append(df)
        print(f"Loaded {ticker}: {len(df)} rows")

    stacked = pd.concat(frames, ignore_index=True)
    csv_path = OUT_DIR / f"{args.output_prefix}_feature_panel.csv"
    parquet_path = OUT_DIR / f"{args.output_prefix}_feature_panel.parquet"
    summary_path = OUT_DIR / f"{args.output_prefix}_feature_panel_summary.json"
    stacked.to_csv(csv_path, index=False)
    try:
        stacked.to_parquet(parquet_path, index=False)
    except Exception as exc:
        print(f"  ! parquet write skipped: {exc}")

    summary = build_summary(stacked, tickers)
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Wrote {csv_path} ({len(stacked)} rows)")
    print(f"Wrote {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
