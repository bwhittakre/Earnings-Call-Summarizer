#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Side-by-side: LLM narrative dimension scores vs quant dimension z-scores.
=========================================================================

Joins the LLM output (llm_dimension_scores) to the quant spine
(dimension_scores) on `fiscal_period` for the five overlapping dimensions
so you can eyeball, per quarter, whether the qualitative narrative read agrees
with the quantitative surprise/revision signal.

Note the two are on different scales (LLM = fixed -2..+2 health score; quant =
z-score vs history), so compare DIRECTION and relative magnitude, not absolute
values. This is a coverage/quality sanity check for the pilot, not a fit metric.

    python "Structured Narrative/build_comparison.py"
    python "Structured Narrative/build_comparison.py" --ticker AMZN
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from excel_export import write_excel  # noqa: E402
from output_paths import company_artifact, resolve_read_parquet_or_csv  # noqa: E402

# LLM dimension key -> quant z column in dimension_scores.
COMPARABLE = {
    "demand": "dim_demand_z",
    "margins": "dim_margins_z",
    "earnings_power": "dim_earnings_power_z",
    "capital_allocation": "dim_capital_allocation_z",
    "guidance": "dim_guidance_z",
}


def _read(ticker: str, stem: str) -> pd.DataFrame:
    path = resolve_read_parquet_or_csv(ticker, stem, layer="parquet")
    if path is None:
        path = resolve_read_parquet_or_csv(ticker, stem, layer="csv")
    if path is None:
        raise FileNotFoundError(
            f"Missing {stem}.parquet/.csv for {ticker.upper()} "
            f"(checked parquet/ and csv/ layers plus legacy flat files)."
        )
    return pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)


def main() -> int:
    ap = argparse.ArgumentParser(description="LLM vs quant dimension comparison.")
    ap.add_argument("--ticker", default="AMZN", help="Ticker to compare.")
    args = ap.parse_args()
    ticker = args.ticker.upper()

    llm = _read(ticker, "llm_dimension_scores")
    quant = _read(ticker, "dimension_scores")

    llm_cmp = llm[llm["dimension"].isin(COMPARABLE)].copy()

    # Wide LLM: one row per fiscal_period, columns dim_<x>_llm.
    llm_wide = (
        llm_cmp.pivot_table(
            index="fiscal_period", columns="dimension", values="score", aggfunc="first"
        )
        .rename(columns={k: f"dim_{k}_llm" for k in COMPARABLE})
        .reset_index()
    )

    quant_cols = ["fiscal_period"] + [c for c in COMPARABLE.values() if c in quant.columns]
    merged = llm_wide.merge(quant[quant_cols], on="fiscal_period", how="left")

    # Order columns: fiscal_period, then per-dimension (llm, z) pairs.
    ordered = ["fiscal_period"]
    for dim, zcol in COMPARABLE.items():
        lcol = f"dim_{dim}_llm"
        if lcol in merged.columns:
            ordered.append(lcol)
        if zcol in merged.columns:
            ordered.append(zcol)
    ordered += [c for c in merged.columns if c not in ordered]
    merged = merged[ordered].sort_values("fiscal_period").reset_index(drop=True)

    stem = "llm_vs_quant_FY2024"
    csv_path = company_artifact(ticker, "csv", stem, "csv", mkdir=True)
    xlsx_path = company_artifact(ticker, "workbooks", stem, "xlsx", mkdir=True)
    merged.to_csv(csv_path, index=False)
    try:
        write_excel(merged, str(xlsx_path))
    except Exception as exc:
        print(f"  ! xlsx write skipped: {exc}")

    with pd.option_context("display.width", 160, "display.max_columns", None):
        print(merged.to_string(index=False))
    print(f"\nWrote {csv_path}")
    print(f"Wrote {xlsx_path}")
    print("\nScales differ: LLM score is -2..+2 (narrative health); quant is a "
          "z-score vs AMZN history. Compare direction/rank, not absolute values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
