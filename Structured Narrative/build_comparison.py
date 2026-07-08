#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Side-by-side: LLM narrative dimension scores vs quant dimension z-scores.
=========================================================================

Joins the LLM output (AMZN_llm_dimension_scores) to the quant spine
(AMZN_dimension_scores) on `fiscal_period` for the five overlapping dimensions
so you can eyeball, per quarter, whether the qualitative narrative read agrees
with the quantitative surprise/revision signal.

Note the two are on different scales (LLM = fixed -2..+2 health score; quant =
z-score vs history), so compare DIRECTION and relative magnitude, not absolute
values. This is a coverage/quality sanity check for the pilot, not a fit metric.

    python "Structured Narrative/build_comparison.py"
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
OUT_DIR = HERE / "output"

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from excel_export import write_excel  # noqa: E402

# LLM dimension key -> quant z column in AMZN_dimension_scores.
COMPARABLE = {
    "demand": "dim_demand_z",
    "margins": "dim_margins_z",
    "earnings_power": "dim_earnings_power_z",
    "capital_allocation": "dim_capital_allocation_z",
    "guidance": "dim_guidance_z",
}


def _read(base: str) -> pd.DataFrame:
    p_parquet = OUT_DIR / f"{base}.parquet"
    p_csv = OUT_DIR / f"{base}.csv"
    if p_parquet.exists():
        try:
            return pd.read_parquet(p_parquet)
        except Exception:
            pass
    if p_csv.exists():
        return pd.read_csv(p_csv)
    raise FileNotFoundError(f"Missing {base}.parquet/.csv in {OUT_DIR}")


def main() -> int:
    llm = _read("AMZN_llm_dimension_scores")
    quant = _read("AMZN_dimension_scores")

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

    base = OUT_DIR / "AMZN_llm_vs_quant_FY2024"
    merged.to_csv(base.with_suffix(".csv"), index=False)
    try:
        write_excel(merged, str(base.with_suffix(".xlsx")))
    except Exception as exc:
        print(f"  ! xlsx write skipped: {exc}")

    with pd.option_context("display.width", 160, "display.max_columns", None):
        print(merged.to_string(index=False))
    print(f"\nWrote {base.with_suffix('.csv')}")
    print(f"Wrote {base.with_suffix('.xlsx')}")
    print("\nScales differ: LLM score is -2..+2 (narrative health); quant is a "
          "z-score vs AMZN history. Compare direction/rank, not absolute values.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
