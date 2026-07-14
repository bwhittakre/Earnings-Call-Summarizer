#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validate feature panel quant_z matches the PIT dimension_scores spine.

    python "Structured Narrative/validate_panel_quant.py" --ticker MSFT
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from dimension_scorer import QUANT_COMPARABLE_DIMENSIONS  # noqa: E402
from output_paths import resolve_read  # noqa: E402
from quant_loader import load_quant_dim_z  # noqa: E402


def validate_panel_quant(ticker: str, *, tol: float = 1e-3) -> list[str]:
    panel_path = resolve_read(ticker, "feature_panel", "csv", layer="csv")
    if panel_path is None:
        return [f"Missing feature_panel.csv for {ticker}"]

    quant_z = load_quant_dim_z(ticker)
    if not quant_z:
        return []

    panel = pd.read_csv(panel_path)
    errors: list[str] = []

    for _, row in panel.iterrows():
        dim = row["dimension"]
        if dim not in QUANT_COMPARABLE_DIMENSIONS:
            continue
        fp = str(row["fiscal_period"])
        spine_z = quant_z.get(fp, {}).get(dim)
        panel_z = row.get("quant_z")
        if spine_z is None and (panel_z is None or pd.isna(panel_z)):
            continue
        if spine_z is None or panel_z is None or pd.isna(panel_z):
            errors.append(
                f"{fp} {dim}: panel quant_z={panel_z!r} vs spine={spine_z!r}"
            )
            continue
        if abs(float(panel_z) - float(spine_z)) > tol:
            errors.append(
                f"{fp} {dim}: panel quant_z={float(panel_z):.4f} "
                f"!= spine {float(spine_z):.4f}"
            )
    return errors


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate panel quant_z vs dimension_scores.")
    ap.add_argument("--ticker", required=True)
    args = ap.parse_args()
    ticker = args.ticker.upper()

    errors = validate_panel_quant(ticker)
    if not errors:
        print(f"OK: {ticker} panel quant_z matches dimension_scores spine.")
        return 0

    print(f"FAIL: {len(errors)} quant_z mismatch(es) for {ticker}:", file=sys.stderr)
    for err in errors[:20]:
        print(f"  {err}", file=sys.stderr)
    if len(errors) > 20:
        print(f"  ... and {len(errors) - 20} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
