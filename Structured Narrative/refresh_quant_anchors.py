#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Refresh quant z anchors in persisted LLM outputs without re-running the LLM.

Use after narrative_zscore.py recomputes PIT dim_*_z values.

    python "Structured Narrative/refresh_quant_anchors.py" --ticker AMZN
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
from output_paths import (  # noqa: E402
    company_artifact,
    resolve_read,
    resolve_read_parquet_or_csv,
    resolve_read_required,
)
from quant_loader import load_quant_dim_z  # noqa: E402


def _sign(x, eps: float = 1e-9):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if abs(float(x)) < eps:
        return 0
    return 1 if float(x) > 0 else -1


def _agrees(a, b):
    sa, sb = _sign(a), _sign(b)
    if sa in (None, 0) or sb in (None, 0):
        return None
    return sa == sb


def _gap(surprise_mag, quant_z):
    if quant_z is None or (isinstance(quant_z, float) and pd.isna(quant_z)):
        return None
    q = max(-2.0, min(2.0, float(quant_z)))
    return round(float(surprise_mag) - q, 2)


def refresh_dimension_view(ticker: str, quant_z: dict[str, dict[str, float | None]]) -> dict:
    view_path = resolve_read_required(ticker, "dimension_view", "json", layer="json")
    view = json.loads(view_path.read_text(encoding="utf-8"))
    for q in view.get("quarters", []):
        fp = q["fiscal_period"]
        for d in q.get("dimensions", []):
            dim = d["dimension"]
            if dim in QUANT_COMPARABLE_DIMENSIONS:
                d["quant_z"] = quant_z.get(fp, {}).get(dim)
    out = company_artifact(ticker, "json", "dimension_view", "json", mkdir=True)
    out.write_text(json.dumps(view, indent=2), encoding="utf-8")
    print(f"Updated {out}")
    return view


def refresh_delta(ticker: str, quant_z: dict[str, dict[str, float | None]]) -> None:
    csv_path = resolve_read(ticker, "dimension_delta", "csv", layer="csv")
    if csv_path is None:
        print("  ! dimension_delta.csv not found; skipping delta refresh")
        return
    df = pd.read_csv(csv_path)
    if df.empty:
        return

    def row_update(r):
        dim = r["dimension"]
        if not r.get("is_quant_comparable", True):
            return r
        prior_fp = r.get("prior_period")
        current_fp = r["fiscal_period"]
        pz = quant_z.get(str(prior_fp), {}).get(dim) if prior_fp else None
        cz = quant_z.get(str(current_fp), {}).get(dim)
        r["quant_z_prior"] = pz
        r["quant_z_current"] = cz
        if pz is not None and cz is not None and not pd.isna(pz) and not pd.isna(cz):
            r["quant_z_delta"] = round(float(cz) - float(pz), 3)
            r["quant_agrees"] = _agrees(r.get("change_magnitude"), r["quant_z_delta"])
        else:
            r["quant_z_delta"] = None
            r["quant_agrees"] = None
        return r

    df = df.apply(row_update, axis=1)
    csv_out = company_artifact(ticker, "csv", "dimension_delta", "csv", mkdir=True)
    df.to_csv(csv_out, index=False)
    pq_out = company_artifact(ticker, "parquet", "dimension_delta", "parquet", mkdir=True)
    try:
        df.to_parquet(pq_out, index=False)
    except Exception as exc:
        print(f"  ! delta parquet skipped: {exc}")
    print(f"Updated {csv_out}")

    view_path = resolve_read(ticker, "delta_view", "json", layer="json")
    if view_path is None:
        return
    view = json.loads(view_path.read_text(encoding="utf-8"))
    row_lookup = {
        (str(r["fiscal_period"]), str(r["dimension"])): r
        for _, r in df.iterrows()
    }
    for tr in view.get("transitions", []):
        fp = tr["fiscal_period"]
        for d in tr.get("dimensions", []):
            key = (fp, d["dimension"])
            if key in row_lookup:
                src = row_lookup[key]
                d["quant_z_prior"] = src.get("quant_z_prior")
                d["quant_z_current"] = src.get("quant_z_current")
                d["quant_z_delta"] = src.get("quant_z_delta")
                d["quant_agrees"] = src.get("quant_agrees")
    out = company_artifact(ticker, "json", "delta_view", "json", mkdir=True)
    out.write_text(json.dumps(view, indent=2), encoding="utf-8")
    print(f"Updated {out}")


def refresh_surprise(ticker: str, quant_z: dict[str, dict[str, float | None]]) -> None:
    pq_path = resolve_read_parquet_or_csv(ticker, "dimension_surprise", layer="parquet")
    if pq_path is None:
        print("  ! dimension_surprise not found; skipping surprise refresh")
        return
    df = pd.read_parquet(pq_path) if pq_path.suffix == ".parquet" else pd.read_csv(pq_path)
    if df.empty:
        return

    def row_update(r):
        dim = r["dimension"]
        fp = str(r["fiscal_period"])
        if not r.get("is_quant_comparable", True):
            return r
        qz = quant_z.get(fp, {}).get(dim)
        r["quant_z"] = qz
        mag = r.get("surprise_magnitude")
        r["agrees_with_quant"] = _agrees(mag, qz)
        r["narrative_quant_gap"] = _gap(mag, qz)
        return r

    df = df.apply(row_update, axis=1)
    pq_out = company_artifact(ticker, "parquet", "dimension_surprise", "parquet", mkdir=True)
    try:
        df.to_parquet(pq_out, index=False)
    except Exception as exc:
        print(f"  ! surprise parquet skipped: {exc}")
    else:
        print(f"Updated {pq_out}")

    view_path = resolve_read(ticker, "surprise_view", "json", layer="json")
    if view_path is None:
        return
    view = json.loads(view_path.read_text(encoding="utf-8"))
    row_lookup = {
        (str(r["fiscal_period"]), str(r["dimension"])): r
        for _, r in df.iterrows()
    }
    for q in view.get("quarters", []):
        fp = q["fiscal_period"]
        for d in q.get("dimensions", []):
            key = (fp, d["dimension"])
            if key in row_lookup:
                src = row_lookup[key]
                d["quant_z"] = src.get("quant_z")
                d["agrees_with_quant"] = src.get("agrees_with_quant")
                d["narrative_quant_gap"] = src.get("narrative_quant_gap")
    out = company_artifact(ticker, "json", "surprise_view", "json", mkdir=True)
    out.write_text(json.dumps(view, indent=2), encoding="utf-8")
    print(f"Updated {out}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Refresh PIT quant anchors in LLM outputs.")
    ap.add_argument("--ticker", default="AMZN")
    args = ap.parse_args()
    ticker = args.ticker.upper()
    quant_z = load_quant_dim_z(ticker)
    if not quant_z:
        print(f"Error: no dimension_scores for {ticker}", file=sys.stderr)
        return 1
    refresh_dimension_view(ticker, quant_z)
    refresh_delta(ticker, quant_z)
    refresh_surprise(ticker, quant_z)
    print(f"\nDone: refreshed PIT quant anchors for {ticker}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
