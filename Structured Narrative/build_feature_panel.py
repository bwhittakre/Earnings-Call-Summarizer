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
from quant_loader import (  # noqa: E402
    load_quant_dim_z,
    load_quant_guidance_revision_z_pit,
    load_quant_spine_meta,
    load_quant_z_fullsample,
    load_quant_z_pit,
)
from quant_mapping import FEATURE_AVAILABILITY_MANIFEST, quant_family_for, quant_mapping_for  # noqa: E402
from period_dates import (  # noqa: E402
    apply_feature_availability_dates,
    enrich_panel_period_columns,
    period_end_sort_columns,
    resolve_period_end_date,
)
from quant_panel import agrees, apply_derived_features, narrative_quant_gap  # noqa: E402

PANEL_COLUMNS = [
    "ticker",
    "fiscal_period",
    "period_end_date",
    "period_end_calendar_quarter",
    "dimension",
    "as_of_date",
    "earnings_date",
    "feature_availability_date",
    "quant_mapping",
    "quant_family",
    "quant_z",
    "quant_z_pit",
    "quant_z_fullsample",
    "quant_guidance_revision_z_pit",
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
    "novelty_direction",
    "narrative_novelty",
    "novelty_rationale",
    "novelty_evidence_supported_pct",
    "has_level",
    "has_delta",
    "has_surprise",
    "has_novelty",
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
    nd = row.get("novelty_direction")
    if nd == "high_novelty":
        parts.append("novelty_high")
    elif nd == "moderate_novelty":
        parts.append("novelty_moderate")
    elif nd == "low_novelty":
        parts.append("novelty_low")
    if row.get("any_quant_divergence") is True or row.get("is_divergence") is True:
        parts.append("quant_diverges")
    return "|".join(parts)


def build_spine(quant: pd.DataFrame, ticker: str) -> pd.DataFrame:
    quant_z_pit_map = load_quant_z_pit(ticker)
    quant_z_full_map = load_quant_z_fullsample(ticker)
    guidance_rev_map = load_quant_guidance_revision_z_pit(ticker)
    meta_map = load_quant_spine_meta(ticker)
    rows: list[dict] = []
    for _, row in quant.iterrows():
        fp = str(row["fiscal_period"])
        meta = meta_map.get(fp, {})
        earn = meta.get("earnings_date") or row.get("earnings_date")
        model_date = meta.get("model_date")
        period_end = meta.get("period_end_date") or row.get("fiscal_quarter_end")
        for dim in ALL_DIMENSIONS:
            rec = {
                "ticker": ticker,
                "fiscal_period": fp,
                "period_end_date": period_end,
                "dimension": dim,
                "as_of_date": earn,
                "earnings_date": earn,
                "model_date": model_date,
                "quant_mapping": quant_mapping_for(dim),
                "quant_family": quant_family_for(dim),
                "alpha_spec_0_90": row.get("alpha_spec_0_90"),
                "alpha_spec_0_90_z": row.get("alpha_spec_0_90_z"),
                "alpha_spec_0_90_complete": row.get("alpha_spec_0_90_complete"),
            }
            if dim in QUANT_COMPARABLE_DIMENSIONS:
                if dim == "guidance":
                    rec["quant_z_pit"] = None
                    rec["quant_z"] = None
                    rec["quant_z_fullsample"] = None
                    rec["quant_guidance_revision_z_pit"] = guidance_rev_map.get(fp)
                else:
                    qz = quant_z_pit_map.get(fp, {}).get(dim)
                    rec["quant_z_pit"] = qz
                    rec["quant_z"] = qz
                    rec["quant_z_fullsample"] = quant_z_full_map.get(fp, {}).get(dim)
                    rec["quant_guidance_revision_z_pit"] = None
            else:
                rec["quant_z_pit"] = None
                rec["quant_z"] = None
                rec["quant_z_fullsample"] = None
                rec["quant_guidance_revision_z_pit"] = None
            rows.append(rec)
    return pd.DataFrame(rows)


def build_spine_from_level(level: pd.DataFrame, ticker: str) -> pd.DataFrame:
    """Build panel spine from LLM level rows when quant dimension_scores are unavailable."""
    rows: list[dict] = []
    for _, row in level.iterrows():
        fp = str(row["fiscal_period"])
        earn = row.get("as_of_date")
        ped = resolve_period_end_date(ticker, fp)
        rec = {
            "ticker": ticker,
            "fiscal_period": fp,
            "period_end_date": ped.isoformat() if ped else None,
            "dimension": row["dimension"],
            "as_of_date": earn,
            "earnings_date": earn,
            "model_date": None,
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


def prepare_novelty(novelty: pd.DataFrame) -> pd.DataFrame:
    if novelty.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "fiscal_period",
                "dimension",
                "as_of_date",
                "novelty_direction",
                "narrative_novelty",
                "novelty_rationale",
                "novelty_evidence_supported_pct",
            ]
        )
    df = novelty.copy()
    df["novelty_evidence_supported_pct"] = df.apply(
        lambda r: _evidence_pct(r.get("n_evidence_verified"), r.get("n_evidence"), r.get("evidence_verified")),
        axis=1,
    )
    return df.rename(columns={"rationale": "novelty_rationale", "novelty_magnitude": "narrative_novelty"})[
        [
            "ticker",
            "fiscal_period",
            "dimension",
            "as_of_date",
            "novelty_direction",
            "narrative_novelty",
            "novelty_rationale",
            "novelty_evidence_supported_pct",
        ]
    ]


def _overlay_live_quant(panel: pd.DataFrame) -> pd.DataFrame:
    """Recompute surprise quant agreement from spine quant_z_pit (source of truth)."""
    df = panel.copy()

    def row_update(r):
        dim = r["dimension"]
        if dim not in QUANT_COMPARABLE_DIMENSIONS:
            return r
        mag = r.get("surprise_magnitude")
        if dim == "guidance":
            qz = r.get("quant_guidance_revision_z_pit")
        else:
            qz = r.get("quant_z_pit")
            if qz is None or (isinstance(qz, float) and pd.isna(qz)):
                qz = r.get("quant_z")
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
    novelty: pd.DataFrame,
    *,
    full_spine: bool,
) -> pd.DataFrame:
    keys = ["ticker", "fiscal_period", "dimension"]
    panel = spine.merge(level, on=keys, how="left", suffixes=("", "_level"))
    panel = panel.merge(delta, on=keys, how="left", suffixes=("", "_delta"))
    panel = panel.merge(surprise, on=keys, how="left", suffixes=("", "_surprise"))
    panel = panel.merge(novelty, on=keys, how="left", suffixes=("", "_novelty"))

    for src in ("_level", "_delta", "_surprise", "_novelty"):
        col = f"as_of_date{src}"
        if col in panel.columns:
            panel["as_of_date"] = panel["as_of_date"].fillna(panel[col])
            panel = panel.drop(columns=[col])

    panel = apply_feature_availability_dates(panel)
    panel = enrich_panel_period_columns(panel)
    if "model_date" in panel.columns:
        panel = panel.drop(columns=["model_date"])

    panel["has_level"] = panel["llm_level"].notna()
    panel["has_delta"] = panel["change_magnitude"].notna()
    panel["has_surprise"] = panel["surprise_magnitude"].notna()
    panel["has_novelty"] = panel["narrative_novelty"].notna()

    panel = _overlay_live_quant(panel)
    panel = apply_derived_features(panel)
    panel["signal_stack"] = panel.apply(_signal_stack, axis=1)

    if not full_spine:
        mask = panel["has_level"] | panel["has_delta"] | panel["has_surprise"] | panel["has_novelty"]
        panel = panel.loc[mask].copy()

    sort_cols = [c for c in period_end_sort_columns() if c in panel.columns]
    if sort_cols:
        panel = panel.sort_values(sort_cols).reset_index(drop=True)
    else:
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
            "has_novelty": int(panel["has_novelty"].sum()),
            "is_divergence": int(panel["is_divergence"].sum()),
            "any_quant_divergence": int(panel["any_quant_divergence"].sum()),
        },
        "fiscal_periods": sorted(panel["fiscal_period"].unique().tolist()),
        "dimensions": ALL_DIMENSIONS,
        "top_divergences": top_rows,
    }


def write_feature_availability_manifest(ticker: str) -> None:
    path = company_artifact(ticker, "json", "feature_availability", "json", mkdir=True)
    path.write_text(json.dumps(FEATURE_AVAILABILITY_MANIFEST, indent=2), encoding="utf-8")


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
    write_feature_availability_manifest(ticker)
    spine_path = company_artifact(ticker, "csv", "research_spine", "csv", mkdir=True)
    from spine_export import panel_to_spine  # noqa: E402

    panel_to_spine(panel).to_csv(spine_path, index=False)

    print(f"Wrote {csv_path}")
    print(f"Wrote {spine_path}")
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
    novelty_df = _read_optional(ticker, "dimension_novelty", layer="parquet")
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

    if novelty_df is None:
        novelty_df = pd.DataFrame(
            columns=[
                "ticker",
                "fiscal_period",
                "dimension",
                "as_of_date",
                "novelty_direction",
                "novelty_magnitude",
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
        prepare_novelty(novelty_df),
        full_spine=full_spine,
    )
    if output_quarters is not None:
        panel = panel.loc[panel["fiscal_period"].isin(output_quarters)].copy()
        sort_cols = [c for c in period_end_sort_columns() if c in panel.columns]
        panel = panel.sort_values(sort_cols or ["fiscal_period", "dimension"]).reset_index(drop=True)
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
            sort_cols = [c for c in period_end_sort_columns() if c in panel.columns]
            panel = panel.sort_values(sort_cols or ["fiscal_period", "dimension"]).reset_index(drop=True)

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
