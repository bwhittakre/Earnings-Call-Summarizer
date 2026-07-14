#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unified long-format feature panel: Focus 1 level + Focus 2 delta + Focus 3 surprise + quant spine.

    python "Structured Narrative/build_feature_panel.py"
    python "Structured Narrative/build_feature_panel.py" --ticker AMZN --full-spine
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
from company_config import get_company  # noqa: E402
from quarter_registry import is_quarter_complete, load_registry  # noqa: E402
from dimension_scorer import ALL_DIMENSIONS, QUANT_COMPARABLE_DIMENSIONS  # noqa: E402
from output_paths import company_artifact, resolve_read, resolve_read_parquet_or_csv  # noqa: E402
from panel_html import (  # noqa: E402
    EvidenceLookups,
    build_evidence_lookups,
    build_single_ticker_html,
)
from quant_loader import load_quant_dim_z  # noqa: E402
from quant_panel import agrees, apply_derived_features, narrative_quant_gap  # noqa: E402

PANEL_COLUMNS = [
    "ticker",
    "fiscal_period",
    "dimension",
    "as_of_date",
    "earnings_date",
    "quant_z",
    "alpha_spec_0_90",
    "alpha_spec_0_90_z",
    "alpha_spec_0_90_complete",
    "llm_level",
    "level_rationale",
    "level_evidence_supported_pct",
    "prior_period",
    "change_direction",
    "change_magnitude",
    "score_delta",
    "quant_z_delta",
    "delta_rationale",
    "delta_evidence_supported_pct",
    "surprise_direction",
    "surprise_magnitude",
    "agrees_with_quant",
    "narrative_quant_gap",
    "surprise_rationale",
    "surprise_evidence_supported_pct",
    "has_level",
    "has_delta",
    "has_surprise",
    "level_quant_sign_match",
    "delta_quant_sign_match",
    "level_diverges",
    "delta_diverges",
    "surprise_diverges",
    "any_quant_divergence",
    "is_divergence",
    "has_quant_z",
    "abs_narrative_quant_gap",
    "surprise_quant_interaction",
    "llm_level_4q_mean",
    "change_magnitude_4q_mean",
    "signal_stack",
]


def _read(ticker: str, stem: str, *, layer: str = "parquet") -> pd.DataFrame:
    src = resolve_read_parquet_or_csv(ticker, stem, layer=layer)
    if src is None:
        raise FileNotFoundError(
            f"Missing {layer}/{stem}.parquet/.csv for {ticker.upper()} "
            f"(also checked legacy flat path)."
        )
    return pd.read_parquet(src) if src.suffix == ".parquet" else pd.read_csv(src)


def _evidence_pct(n_verified, n_total, verified_flag) -> float | None:
    if pd.notna(n_total) and int(n_total) > 0:
        return round(float(n_verified) / float(n_total), 4)
    if verified_flag is True:
        return 1.0
    if verified_flag is False:
        return 0.0
    return None


def _signal_stack(row: pd.Series) -> str:
    parts: list[str] = []
    ll = row.get("llm_level")
    if pd.notna(ll):
        if ll > 0.3:
            parts.append("bullish_level")
        elif ll < -0.3:
            parts.append("bearish_level")
        else:
            parts.append("neutral_level")
    cm = row.get("change_magnitude")
    if pd.notna(cm):
        if cm > 0.05:
            parts.append("delta_up")
        elif cm < -0.05:
            parts.append("delta_down")
        else:
            parts.append("delta_flat")
    sd = row.get("surprise_direction")
    if sd == "more_bullish_than_expected":
        parts.append("surprise_bullish")
    elif sd == "more_bearish_than_expected":
        parts.append("surprise_bearish")
    elif sd == "in_line":
        parts.append("surprise_inline")
    if row.get("any_quant_divergence") is True or row.get("is_divergence") is True:
        parts.append("quant_diverges")
    return "|".join(parts)


def build_spine(quant: pd.DataFrame, ticker: str) -> pd.DataFrame:
    quant_z_map = load_quant_dim_z(ticker)
    rows: list[dict] = []
    for _, row in quant.iterrows():
        fp = str(row["fiscal_period"])
        meta = {
            "ticker": ticker,
            "fiscal_period": fp,
            "as_of_date": row.get("earnings_date"),
            "earnings_date": row.get("earnings_date"),
            "alpha_spec_0_90": row.get("alpha_spec_0_90"),
            "alpha_spec_0_90_z": row.get("alpha_spec_0_90_z"),
            "alpha_spec_0_90_complete": row.get("alpha_spec_0_90_complete"),
        }
        for dim in ALL_DIMENSIONS:
            rec = dict(meta)
            rec["dimension"] = dim
            if dim in QUANT_COMPARABLE_DIMENSIONS:
                rec["quant_z"] = quant_z_map.get(fp, {}).get(dim)
            else:
                rec["quant_z"] = None
            rows.append(rec)
    return pd.DataFrame(rows)


def build_spine_from_level(level: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Build panel spine from LLM level rows when quant dimension_scores are unavailable."""
    rows: list[dict] = []
    for _, row in level.iterrows():
        rec = {
            "ticker": ticker,
            "fiscal_period": row["fiscal_period"],
            "dimension": row["dimension"],
            "as_of_date": row.get("as_of_date"),
            "earnings_date": row.get("as_of_date"),
            "quant_z": None,
            "alpha_spec_0_90": None,
            "alpha_spec_0_90_z": None,
            "alpha_spec_0_90_complete": None,
        }
        rows.append(rec)
    return pd.DataFrame(rows)


def _read_optional(ticker: str, stem: str, *, layer: str = "parquet") -> pd.DataFrame | None:
    try:
        return _read(ticker, stem, layer=layer)
    except FileNotFoundError:
        return None


def prepare_level(level: pd.DataFrame) -> pd.DataFrame:
    df = level.copy()
    df["level_evidence_supported_pct"] = df.apply(
        lambda r: _evidence_pct(r.get("n_evidence_verified"), r.get("n_evidence"), r.get("evidence_verified")),
        axis=1,
    )
    return df.rename(
        columns={
            "score": "llm_level",
            "rationale": "level_rationale",
        }
    )[
        [
            "ticker",
            "fiscal_period",
            "dimension",
            "as_of_date",
            "llm_level",
            "level_rationale",
            "level_evidence_supported_pct",
        ]
    ]


def prepare_delta(delta: pd.DataFrame) -> pd.DataFrame:
    df = delta.copy()
    df["delta_evidence_supported_pct"] = df.apply(
        lambda r: _evidence_pct(r.get("n_evidence_verified"), r.get("n_evidence"), r.get("evidence_verified")),
        axis=1,
    )
    return df.rename(columns={"rationale": "delta_rationale"})[
        [
            "ticker",
            "fiscal_period",
            "dimension",
            "as_of_date",
            "prior_period",
            "change_direction",
            "change_magnitude",
            "score_delta",
            "quant_z_delta",
            "delta_rationale",
            "delta_evidence_supported_pct",
        ]
    ]


def prepare_surprise(surprise: pd.DataFrame) -> pd.DataFrame:
    df = surprise.copy()
    df["surprise_evidence_supported_pct"] = df.apply(
        lambda r: _evidence_pct(r.get("n_evidence_verified"), r.get("n_evidence"), r.get("evidence_verified")),
        axis=1,
    )
    return df.rename(columns={"rationale": "surprise_rationale"})[
        [
            "ticker",
            "fiscal_period",
            "dimension",
            "as_of_date",
            "surprise_direction",
            "surprise_magnitude",
            "agrees_with_quant",
            "narrative_quant_gap",
            "surprise_rationale",
            "surprise_evidence_supported_pct",
        ]
    ]


def _overlay_live_quant(panel: pd.DataFrame) -> pd.DataFrame:
    """Recompute surprise quant agreement from spine quant_z (source of truth)."""
    df = panel.copy()

    def row_update(r):
        if r["dimension"] not in QUANT_COMPARABLE_DIMENSIONS:
            return r
        qz = r.get("quant_z")
        mag = r.get("surprise_magnitude")
        if pd.notna(qz) and pd.notna(mag):
            r["agrees_with_quant"] = agrees(mag, qz)
            r["narrative_quant_gap"] = narrative_quant_gap(mag, qz)
        return r

    return df.apply(row_update, axis=1)


def merge_panel(
    spine: pd.DataFrame,
    level: pd.DataFrame,
    delta: pd.DataFrame,
    surprise: pd.DataFrame,
    *,
    full_spine: bool,
) -> pd.DataFrame:
    keys = ["ticker", "fiscal_period", "dimension"]
    panel = spine.merge(level, on=keys, how="left", suffixes=("", "_level"))
    panel = panel.merge(delta, on=keys, how="left", suffixes=("", "_delta"))
    panel = panel.merge(surprise, on=keys, how="left", suffixes=("", "_surprise"))

    for src in ("_level", "_delta", "_surprise"):
        col = f"as_of_date{src}"
        if col in panel.columns:
            panel["as_of_date"] = panel["as_of_date"].fillna(panel[col])
            panel = panel.drop(columns=[col])

    panel["has_level"] = panel["llm_level"].notna()
    panel["has_delta"] = panel["change_magnitude"].notna()
    panel["has_surprise"] = panel["surprise_magnitude"].notna()

    panel = _overlay_live_quant(panel)
    panel = apply_derived_features(panel)
    panel["signal_stack"] = panel.apply(_signal_stack, axis=1)

    if not full_spine:
        mask = panel["has_level"] | panel["has_delta"] | panel["has_surprise"]
        panel = panel.loc[mask].copy()

    panel = panel.sort_values(["fiscal_period", "dimension"]).reset_index(drop=True)
    for col in PANEL_COLUMNS:
        if col not in panel.columns:
            panel[col] = None
    return panel[PANEL_COLUMNS]


def build_summary(panel: pd.DataFrame, ticker: str) -> dict:
    diverges = panel.loc[panel["is_divergence"] == True]  # noqa: E712
    top = (
        diverges.assign(abs_gap=diverges["narrative_quant_gap"].abs())
        .sort_values("abs_gap", ascending=False)
        .head(10)
    )
    top_rows = [
        {
            "fiscal_period": r["fiscal_period"],
            "dimension": r["dimension"],
            "llm_level": r["llm_level"],
            "quant_z": r["quant_z"],
            "surprise_magnitude": r["surprise_magnitude"],
            "narrative_quant_gap": r["narrative_quant_gap"],
        }
        for _, r in top.iterrows()
    ]
    return {
        "ticker": ticker,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "row_count": int(len(panel)),
        "coverage": {
            "has_level": int(panel["has_level"].sum()),
            "has_delta": int(panel["has_delta"].sum()),
            "has_surprise": int(panel["has_surprise"].sum()),
            "is_divergence": int(panel["is_divergence"].sum()),
            "any_quant_divergence": int(panel["any_quant_divergence"].sum()),
        },
        "fiscal_periods": sorted(panel["fiscal_period"].unique().tolist()),
        "dimensions": ALL_DIMENSIONS,
        "top_divergences": top_rows,
    }


def write_outputs(
    panel: pd.DataFrame,
    summary: dict,
    ticker: str,
    lookups: EvidenceLookups,
) -> None:
    csv_path = company_artifact(ticker, "csv", "feature_panel", "csv", mkdir=True)
    parquet_path = company_artifact(ticker, "parquet", "feature_panel", "parquet", mkdir=True)
    summary_path = company_artifact(ticker, "json", "feature_panel_summary", "json", mkdir=True)
    html_path = company_artifact(ticker, "reports", "feature_panel_report", "html", mkdir=True)

    panel.to_csv(csv_path, index=False)
    try:
        panel.to_parquet(parquet_path, index=False)
    except Exception as exc:
        print(f"  ! parquet write skipped: {exc}")

    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    html_path.write_text(build_single_ticker_html(panel, summary, lookups), encoding="utf-8")

    print(f"Wrote {csv_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {html_path}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Build unified narrative feature panel.")
    parser.add_argument("--ticker", default="AMZN", help="Ticker prefix for input/output files.")
    parser.add_argument(
        "--scope",
        choices=("five_year",),
        help="Quarter scope preset (five_year: AMZN FY2019-Q2 prior, FY2019-Q3..FY2024-Q3 output).",
    )
    parser.add_argument(
        "--full-spine",
        action="store_true",
        help="Include all quant-spine quarters (sparse LLM columns).",
    )
    parser.add_argument(
        "--llm-only",
        action="store_true",
        help="Build panel from LLM scores when quant dimension_scores are missing.",
    )
    parser.add_argument(
        "--from-registry",
        action="store_true",
        help="Filter panel to output quarters marked complete in quarter_registry.json.",
    )
    args = parser.parse_args()
    ticker = args.ticker.upper()

    try:
        level = _read(ticker, "llm_dimension_scores", layer="csv")
        delta = _read(ticker, "dimension_delta", layer="csv")
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    quant = _read_optional(ticker, "dimension_scores", layer="parquet")
    surprise_df = _read_optional(ticker, "dimension_surprise", layer="parquet")
    if surprise_df is None:
        surprise_df = pd.DataFrame(
            columns=[
                "ticker",
                "fiscal_period",
                "dimension",
                "as_of_date",
                "surprise_direction",
                "surprise_magnitude",
                "agrees_with_quant",
                "narrative_quant_gap",
                "rationale",
                "n_evidence_verified",
                "n_evidence",
                "evidence_verified",
            ]
        )

    if quant is not None and not args.llm_only:
        spine = build_spine(quant, ticker)
    elif args.llm_only or quant is None:
        if quant is None and not args.llm_only:
            print(
                f"Note: {ticker}_dimension_scores not found; building LLM-only panel "
                "(quant/surprise columns will be sparse).",
                file=sys.stderr,
            )
        spine = build_spine_from_level(prepare_level(level), ticker)
    else:
        print(f"Error: missing {ticker}_dimension_scores.csv", file=sys.stderr)
        return 1

    company = get_company(ticker, scope=args.scope) if args.scope else None
    output_quarters = set(company.output_quarters) if company else None
    # Scoped runs emit only scored output quarters (prior-only quarters stay delta-only inputs).
    full_spine = args.full_spine and output_quarters is None

    panel = merge_panel(
        spine,
        prepare_level(level),
        prepare_delta(delta),
        prepare_surprise(surprise_df),
        full_spine=full_spine,
    )
    if output_quarters is not None:
        panel = panel.loc[panel["fiscal_period"].isin(output_quarters)].copy()
        panel = panel.sort_values(["fiscal_period", "dimension"]).reset_index(drop=True)
    elif args.from_registry:
        reg = load_registry(ticker)
        fps = [
            fp
            for fp, rec in reg.get("scored_quarters", {}).items()
            if is_quarter_complete(reg, fp)
            and fp not in set(reg.get("prior_only_quarters", []))
        ]
        if fps:
            panel = panel.loc[panel["fiscal_period"].isin(fps)].copy()
            panel = panel.sort_values(["fiscal_period", "dimension"]).reset_index(drop=True)

    summary = build_summary(panel, ticker)
    lookups = build_evidence_lookups(ticker)
    write_outputs(panel, summary, ticker, lookups)

    cov = summary["coverage"]
    print(f"\n{ticker} feature panel: {summary['row_count']} rows")
    print(f"  level={cov['has_level']}  delta={cov['has_delta']}  surprise={cov['has_surprise']}  diverges={cov['is_divergence']}")
    if summary["top_divergences"]:
        print("\nTop divergences (|gap|):")
        for r in summary["top_divergences"][:5]:
            ll = r.get("llm_level")
            qz = r.get("quant_z")
            gap = r.get("narrative_quant_gap")
            ll_s = f"{float(ll):+.1f}" if ll is not None and pd.notna(ll) else "—"
            qz_s = f"{float(qz):+.2f}" if qz is not None and pd.notna(qz) else "—"
            gap_s = f"{float(gap):+.2f}" if gap is not None and pd.notna(gap) else "—"
            print(f"  {r['fiscal_period']} {r['dimension']}: level={ll_s} quant_z={qz_s} gap={gap_s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
