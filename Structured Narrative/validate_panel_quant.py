#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Validate feature panel quant_z_pit matches the PIT dimension_scores spine.

    python "Structured Narrative/validate_panel_quant.py" --ticker MSFT
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from dimension_scorer import QUANT_COMPARABLE_DIMENSIONS  # noqa: E402
from output_paths import company_artifact, resolve_read  # noqa: E402
from quant_loader import load_quant_guidance_revision_z_pit, load_quant_z_pit  # noqa: E402
from quant_mapping import FEATURE_AVAILABILITY_MANIFEST  # noqa: E402


def validate_panel_quant(ticker: str, *, tol: float = 1e-3) -> list[str]:
    panel_path = resolve_read(ticker, "feature_panel", "csv", layer="csv")
    if panel_path is None:
        return [f"Missing feature_panel.csv for {ticker}"]

    quant_z = load_quant_z_pit(ticker)
    guidance_rev = load_quant_guidance_revision_z_pit(ticker)
    if not quant_z and not guidance_rev:
        return []

    panel = pd.read_csv(panel_path)
    errors: list[str] = []

    for _, row in panel.iterrows():
        dim = row["dimension"]
        if dim not in QUANT_COMPARABLE_DIMENSIONS:
            continue
        fp = str(row["fiscal_period"])
        if dim == "guidance":
            spine_z = guidance_rev.get(fp)
            panel_z = row.get("quant_guidance_revision_z_pit")
            call_z = row.get("quant_z_pit")
            if pd.notna(call_z):
                errors.append(f"{fp} guidance: quant_z_pit should be null at call (got {call_z})")
        else:
            spine_z = quant_z.get(fp, {}).get(dim)
            panel_z = row.get("quant_z_pit") if pd.notna(row.get("quant_z_pit")) else row.get("quant_z")
        if spine_z is None and (panel_z is None or pd.isna(panel_z)):
            continue
        if spine_z is None or panel_z is None or pd.isna(panel_z):
            errors.append(f"{fp} {dim}: panel={panel_z!r} vs spine={spine_z!r}")
            continue
        if abs(float(panel_z) - float(spine_z)) > tol:
            errors.append(
                f"{fp} {dim}: panel={float(panel_z):.4f} != spine {float(spine_z):.4f}"
            )

    delayed = panel[panel["dimension"] == "guidance"]
    for _, row in delayed.iterrows():
        if pd.isna(row.get("quant_guidance_revision_z_pit")):
            continue
        t7 = row.get("t7_feature_available_date")
        earn = row.get("earnings_date")
        if pd.isna(t7):
            errors.append(
                f"{row['fiscal_period']} guidance: missing t7_feature_available_date with revision z"
            )
        elif pd.notna(earn) and str(t7)[:10] <= str(earn)[:10]:
            errors.append(
                f"{row['fiscal_period']} guidance: t7_feature_available_date must be after earnings_date"
            )

    return errors


def write_availability_manifest(ticker: str) -> None:
    path = company_artifact(ticker, "json", "feature_availability", "json", mkdir=True)
    path.write_text(json.dumps(FEATURE_AVAILABILITY_MANIFEST, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate panel quant_z_pit vs dimension_scores.")
    ap.add_argument("--ticker", required=True)
    args = ap.parse_args()
    ticker = args.ticker.upper()

    errors = validate_panel_quant(ticker)
    write_availability_manifest(ticker)
    if not errors:
        print(f"OK: {ticker} panel quant_z_pit matches dimension_scores spine.")
        return 0

    print(f"FAIL: {len(errors)} quant_z mismatch(es) for {ticker}:", file=sys.stderr)
    for err in errors[:20]:
        print(f"  {err}", file=sys.stderr)
    if len(errors) > 20:
        print(f"  ... and {len(errors) - 20} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
