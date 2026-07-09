#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Point-in-time consensus context formatter for Focus 3 (narrative surprise).
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from dimension_scorer import QUANT_COMPARABLE_DIMENSIONS
from narrative_zscore import DIMENSIONS, GUIDANCE_ROLES, SURPRISE_ROLE
from output_paths import resolve_read_parquet_or_csv

HERE = Path(__file__).resolve().parent


def load_quant_long(ticker: str = "AMZN") -> pd.DataFrame:
    src = resolve_read_parquet_or_csv(ticker, "narrative_quant", layer="parquet")
    if src is None:
        t = ticker.upper()
        raise FileNotFoundError(
            f"Quant spine not found (parquet/narrative_quant for {t}). "
            f"Run single_company_extractor.py --ticker {t} first."
        )
    return pd.read_parquet(src) if src.suffix == ".parquet" else pd.read_csv(src)


def try_load_quant_long(ticker: str = "AMZN") -> pd.DataFrame | None:
    try:
        return load_quant_long(ticker)
    except FileNotFoundError:
        return None


def _fmt_num(v, unit: str) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "n/a"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if unit == "Currency":
        if abs(f) >= 1000:
            return f"${f:,.0f}M"
        return f"${f:,.2f}M"
    if unit == "Percentage":
        return f"{f:.1f}%"
    return f"{f:,.2f}"


def _fmt_pct(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "n/a"
    try:
        return f"{float(v) * 100:+.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _row_line(label: str, row: pd.Series, *, forward: bool = False) -> str:
    unit = str(row.get("unittype") or "")
    if forward:
        cons = row.get("consensus_pre_mean")
        return f"    {label}: pre-call consensus {_fmt_num(cons, unit)}"
    cons = row.get("consensus_pre_mean")
    act = row.get("actual_value")
    surp = row.get("earnings_surprise_pct")
    return (
        f"    {label}: consensus {_fmt_num(cons, unit)}, "
        f"actual {_fmt_num(act, unit)}, surprise {_fmt_pct(surp)}"
    )


def format_consensus_context(
    fiscal_period: str,
    quant_df: pd.DataFrame | None = None,
    dim_z: dict[str, float | None] | None = None,
    *,
    ticker: str = "AMZN",
) -> str:
    """Render a PIT consensus block for one quarter, grouped by business dimension."""
    df = quant_df if quant_df is not None else try_load_quant_long(ticker)
    if df is None:
        return f"Fiscal period: {fiscal_period}\n(no quant data available)"
    q = df[df["fiscal_period"] == fiscal_period]
    if q.empty:
        return f"Fiscal period: {fiscal_period}\n(no quant data found)"

    present = set(q["measure"].unique())
    lines: list[str] = [f"Fiscal period: {fiscal_period}"]

    if dim_z:
        z_parts = []
        for dim in QUANT_COMPARABLE_DIMENSIONS:
            z = dim_z.get(dim)
            if z is not None and not (isinstance(z, float) and pd.isna(z)):
                z_parts.append(f"{dim} z={float(z):+.2f}")
        if z_parts:
            lines.append(
                f"Standardized surprise vs {ticker.upper()} history (dim z): "
                + ", ".join(z_parts)
            )
    lines.append("")

    reported = q[q["period_role"] == SURPRISE_ROLE]
    forward = q[q["period_role"].isin(GUIDANCE_ROLES)]

    for dim in QUANT_COMPARABLE_DIMENSIONS:
        spec = DIMENSIONS[dim]
        lines.append(f"{dim}:")
        fam = spec["family"]

        if fam == "surprise":
            members = spec["measures"]
            sub = reported[reported["measure"].isin(members)]
            if sub.empty:
                lines.append("    (no reported-quarter measures available)")
            else:
                for _, row in sub.iterrows():
                    label = str(row.get("measure_label") or row.get("measure_desc") or row["measure"])
                    lines.append(_row_line(label, row))
            if dim != "guidance":
                fwd_sub = forward[forward["measure"].isin(members)]
                for _, row in fwd_sub.iterrows():
                    role = row.get("period_role", "")
                    label = (
                        f"{row.get('measure_label', row['measure'])} "
                        f"({role} / {row.get('target_period', '')})"
                    )
                    lines.append(_row_line(label, row, forward=True))
        else:
            sub = forward.copy()
            if not sub.empty:
                rev = sub.dropna(subset=["fwd_estimate_revision_pct"])
                if not rev.empty:
                    for _, row in rev.head(6).iterrows():
                        label = str(row.get("measure_label") or row["measure"])
                        pct = _fmt_pct(row.get("fwd_estimate_revision_pct"))
                        lines.append(
                            f"    {label} ({row.get('period_role')}): "
                            f"post-7d estimate revision {pct} [validation only]"
                        )
                else:
                    lines.append("    (no forward revision data yet)")
            else:
                lines.append("    (no forward consensus rows)")

        lines.append("")

    return "\n".join(lines).rstrip()


def format_level_summary(quarter_view: dict) -> str:
    """Compact Focus 1 level scores for the same quarter (optional LLM context)."""
    lines = [f"LLM narrative levels for {quarter_view.get('fiscal_period', '')}:"]
    for d in quarter_view.get("dimensions", []):
        score = d.get("score")
        score_str = f"{float(score):+.1f}" if isinstance(score, (int, float)) else "n/a"
        rationale = (d.get("rationale") or "").strip()
        lines.append(f"- {d.get('dimension')}: {score_str} — {rationale}")
    return "\n".join(lines)
