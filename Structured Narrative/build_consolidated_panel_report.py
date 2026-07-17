#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build cross-company consolidated feature panel HTML report.

    python "Structured Narrative/build_consolidated_panel_report.py"
    python "Structured Narrative/build_consolidated_panel_report.py" --tickers AMZN MSFT NVDA AAPL
    python "Structured Narrative/build_consolidated_panel_report.py" --sector mega_cap_tech
    python "Structured Narrative/build_consolidated_panel_report.py" --quarter FY2025-Q4
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from asof_alpha import apply_asof_alpha_labels  # noqa: E402
from company_config import PILOT_OUTPUT_QUARTERS, PILOT_TICKERS  # noqa: E402
from coverage import annotate_included, build_coverage_summary  # noqa: E402
from dimension_order import DEFAULT_PRESET, prepare_consolidated_panel  # noqa: E402
from export_modeling_spine import filter_registry_complete, load_panel  # noqa: E402
from excel_export import write_cross_section_panel_workbook  # noqa: E402
from fiscal_period_util import fiscal_period_sort_key  # noqa: E402
from output_paths import cross_company_artifact, cross_company_layer, company_artifact, ensure_cross_company_tree  # noqa: E402
from panel_html import build_consolidated_html, build_evidence_lookups, summarize_ticker_quarter  # noqa: E402
from period_dates import (  # noqa: E402
    apply_feature_availability_dates,
    apply_investable_cross_section_columns,
    calendar_quarter_sort_key,
    enrich_panel_period_columns,
)
from spine_export import (  # noqa: E402
    CONSOLIDATED_SPINE_COLUMNS,
    panel_to_spine,
    standardize_surprise_novelty_exclusivity,
    validate_spine_rules,
)

SECTORS_DIR = REPO_ROOT / "config" / "sectors"
PANEL_CHUNKS_DIR = "panel_chunks"

EIGHT_QUARTER_SCOPE = tuple(PILOT_OUTPUT_QUARTERS)


def load_sector_tickers(sector: str) -> list[str]:
    path = SECTORS_DIR / f"{sector.strip()}.txt"
    if not path.is_file():
        known = sorted(p.stem for p in SECTORS_DIR.glob("*.txt")) if SECTORS_DIR.is_dir() else []
        raise FileNotFoundError(
            f"Sector file not found: {path}. Known sectors: {', '.join(known) or '(none)'}"
        )
    tickers: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tickers.append(line.upper())
    if not tickers:
        raise ValueError(f"No tickers in sector file {path}")
    return tickers


def resolve_tickers(args) -> tuple[list[str], str | None]:
    if args.sector and args.tickers:
        raise ValueError("Use either --sector or --tickers, not both.")
    if args.sector:
        return load_sector_tickers(args.sector), args.sector
    tickers = [t.upper() for t in (args.tickers or list(PILOT_TICKERS))]
    return tickers, None


def latest_common_quarter(tickers: list[str], stacked: pd.DataFrame) -> str | None:
    sets = [
        set(stacked.loc[stacked["ticker"] == t, "fiscal_period"].unique())
        for t in tickers
    ]
    if not sets:
        return None
    common = set.intersection(*sets) if len(sets) > 1 else sets[0]
    if not common:
        all_fps = stacked["fiscal_period"].unique().tolist()
        return sorted(all_fps, key=fiscal_period_sort_key)[-1] if all_fps else None
    return sorted(common, key=fiscal_period_sort_key)[-1]


def default_period_bucket(stacked: pd.DataFrame) -> str | None:
    """Latest period-end calendar quarter with the most tickers represented."""
    if "period_end_calendar_quarter" not in stacked.columns:
        stacked = enrich_panel_period_columns(stacked)
    counts = stacked.groupby("period_end_calendar_quarter")["ticker"].nunique()
    counts = counts[counts.index.notna()]
    if counts.empty:
        return None
    return max(counts.index.tolist(), key=lambda b: (calendar_quarter_sort_key(str(b)), int(counts[b])))


def period_buckets_from_panel(stacked: pd.DataFrame) -> list[str]:
    if "period_end_calendar_quarter" not in stacked.columns:
        stacked = enrich_panel_period_columns(stacked)
    buckets = [
        str(b)
        for b in stacked["period_end_calendar_quarter"].dropna().unique().tolist()
    ]
    return sorted(buckets, key=calendar_quarter_sort_key, reverse=True)


def filter_quarters(panel: pd.DataFrame, quarters: list[str] | None) -> pd.DataFrame:
    if not quarters:
        return panel
    allowed = set(quarters)
    return panel[panel["fiscal_period"].isin(allowed)].copy()


def build_summary_json(
    stacked: pd.DataFrame,
    tickers: list[str],
    *,
    sector: str | None,
    default_quarter: str | None,
    default_period_bucket: str | None,
    period_buckets: list[str],
    loaded_tickers: list[str],
    skipped_tickers: list[str],
    quarter_scope: list[str] | None = None,
    prior_quarters: list[str] | None = None,
) -> dict:
    fiscal_periods = sorted(stacked["fiscal_period"].unique().tolist(), key=fiscal_period_sort_key)
    by_ticker: dict[str, dict] = {}
    for ticker in loaded_tickers:
        sub = stacked[stacked["ticker"] == ticker]
        periods = sorted(sub["fiscal_period"].unique().tolist(), key=fiscal_period_sort_key)
        quarter_meta: list[dict] = []
        for fp in periods:
            qsub = sub[sub["fiscal_period"] == fp]
            meta_row = qsub.iloc[0]
            quarter_meta.append(
                {
                    "fiscal_period": fp,
                    "period_end_date": str(meta_row.get("period_end_date"))[:10]
                    if pd.notna(meta_row.get("period_end_date"))
                    else None,
                    "period_end_calendar_quarter": meta_row.get("period_end_calendar_quarter"),
                    "earnings_date": str(meta_row.get("earnings_date"))[:10]
                    if pd.notna(meta_row.get("earnings_date"))
                    else None,
                    "feature_availability_date": str(meta_row.get("feature_availability_date"))[:10]
                    if pd.notna(meta_row.get("feature_availability_date"))
                    else None,
                }
            )
        by_quarter = {}
        for fp in periods:
            qsub = sub[sub["fiscal_period"] == fp]
            by_quarter[fp] = summarize_ticker_quarter(qsub)
        by_ticker[ticker] = {
            "rows": int(len(sub)),
            "quarters": quarter_meta,
            "fiscal_periods": periods,
            "divergence_count": int(sub["is_divergence"].fillna(False).sum()),
            "by_quarter": by_quarter,
        }

    chunks_dir = cross_company_layer("json", mkdir=True) / PANEL_CHUNKS_DIR
    chunks_dir.mkdir(parents=True, exist_ok=True)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tickers_requested": tickers,
        "tickers_loaded": loaded_tickers,
        "tickers_skipped": skipped_tickers,
        "sector": sector,
        "default_quarter": default_quarter,
        "default_period_bucket": default_period_bucket,
        "period_end_calendar_quarters": period_buckets,
        "quarter_scope": quarter_scope,
        "prior_quarters_excluded": prior_quarters,
        "fiscal_periods": fiscal_periods,
        "row_count": int(len(stacked)),
        "by_ticker": by_ticker,
        "scale_hooks": {
            "panel_chunks_dir": f"cross_company/json/{PANEL_CHUNKS_DIR}/",
            "panel_chunks_convention": (
                "Future lazy-load: one JSON sidecar per ticker at "
                f"output/cross_company/json/{PANEL_CHUNKS_DIR}/{{TICKER}}.json "
                "containing evidence lookups and panel rows for that ticker."
            ),
            "sector_manifest_dir": "config/sectors/",
            "future_grouping": (
                "Sector/industry accordion groups can be added by joining ticker metadata "
                "(GICS/Barra from IRIS_UNIV) without changing the HTML shell."
            ),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Build consolidated cross-company feature panel report.")
    ap.add_argument("--tickers", nargs="+", help="Tickers to include (default: pilot tickers).")
    ap.add_argument("--sector", help="Load tickers from config/sectors/{name}.txt")
    ap.add_argument(
        "--quarter",
        metavar="yyyy-Qn",
        help="Default period-end calendar bucket for Compare mode (e.g. 2025-Q1).",
    )
    ap.add_argument(
        "--quarters",
        nargs="+",
        metavar="FYyyyy-Qn",
        help="Restrict to these fiscal periods (e.g. FY2025-Q1 .. FY2026-Q4).",
    )
    ap.add_argument(
        "--scope",
        choices=("fy2025_26",),
        help="Preset: FY2025 Q1-Q4 + FY2026 Q1-Q4 output quarters.",
    )
    ap.add_argument(
        "--full-history-tickers",
        nargs="+",
        default=[],
        help="Tickers that keep all panel rows (ignore --quarters/--scope filter).",
    )
    ap.add_argument(
        "--research-ticker",
        default="AMZN",
        help="Ticker for separate full-history research spine export (default: AMZN).",
    )
    ap.add_argument(
        "--output-stem",
        default="consolidated_feature_panel",
        help="Output file stem under cross_company/{reports,json,csv}/.",
    )
    ap.add_argument(
        "--dimension-order",
        default=DEFAULT_PRESET,
        choices=("pipeline", "fundamentals_context", "behavioral", "research_note", "risk_first"),
        help="Thematic dimension row order for consolidated panel (default: fundamentals_context / Option B).",
    )
    args = ap.parse_args()
    full_history = {t.upper() for t in args.full_history_tickers}

    quarter_scope: list[str] | None = None
    if args.scope == "fy2025_26":
        quarter_scope = list(EIGHT_QUARTER_SCOPE)
    elif args.quarters:
        quarter_scope = [q.upper() for q in args.quarters]

    try:
        tickers, sector = resolve_tickers(args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    frames: list[pd.DataFrame] = []
    loaded: list[str] = []
    skipped: list[str] = []
    for ticker in tickers:
        try:
            panel = load_panel(ticker)
            panel = filter_registry_complete(panel, ticker)
            if quarter_scope and ticker not in full_history:
                panel = filter_quarters(panel, quarter_scope)
            if panel.empty:
                skipped.append(ticker)
                print(f"  ! Skipping {ticker}: no rows in quarter scope", file=sys.stderr)
                continue
            if "ticker" not in panel.columns:
                panel = panel.copy()
                panel.insert(0, "ticker", ticker)
            frames.append(panel)
            loaded.append(ticker)
            print(f"Loaded {ticker}: {len(panel)} rows")
        except FileNotFoundError:
            skipped.append(ticker)
            print(f"  ! Skipping {ticker}: feature_panel.csv not found", file=sys.stderr)

    if not frames:
        print("No feature panels loaded.", file=sys.stderr)
        return 1

    stacked = pd.concat(frames, ignore_index=True)
    stacked = standardize_surprise_novelty_exclusivity(stacked)
    stacked = enrich_panel_period_columns(stacked)
    if "call_feature_available_date" not in stacked.columns:
        stacked = apply_feature_availability_dates(stacked)
    # Recompute cohort as-of across stacked tickers (per period_end_calendar_quarter).
    stacked = apply_investable_cross_section_columns(stacked)
    stacked = apply_asof_alpha_labels(stacked, fetch_if_missing=True)
    stacked = annotate_included(stacked)
    stacked = prepare_consolidated_panel(stacked, args.dimension_order)

    coverage = build_coverage_summary(
        tickers_requested=tickers,
        tickers_loaded=loaded,
        tickers_skipped=skipped,
        quarter_scope=quarter_scope,
        stacked=stacked,
    )

    period_buckets = period_buckets_from_panel(stacked)
    default_bucket = args.quarter
    if not default_bucket:
        default_bucket = default_period_bucket(stacked)
    if not default_bucket and period_buckets:
        default_bucket = period_buckets[0]

    default_quarter = latest_common_quarter(loaded, stacked)
    lookups_by_ticker = {t: build_evidence_lookups(t) for t in loaded}

    summary = build_summary_json(
        stacked,
        tickers,
        sector=sector,
        default_quarter=default_quarter,
        default_period_bucket=default_bucket,
        period_buckets=period_buckets,
        loaded_tickers=loaded,
        skipped_tickers=skipped,
        quarter_scope=quarter_scope,
        prior_quarters=["FY2024-Q4"],
    )
    summary["coverage"] = coverage

    stem = args.output_stem
    ensure_cross_company_tree()
    html_path = cross_company_artifact("reports", stem, "html", mkdir=True)
    summary_path = cross_company_artifact("json", f"{stem}_summary", "json", mkdir=True)
    coverage_path = cross_company_artifact("json", f"{stem}_coverage", "json", mkdir=True)
    csv_path = cross_company_artifact("csv", stem, "csv", mkdir=True)
    spine_path = cross_company_artifact("csv", "cross_section_spine", "csv", mkdir=True)

    cross_section = stacked.copy()
    if quarter_scope:
        cross_section = filter_quarters(cross_section, quarter_scope)
    spine_df = panel_to_spine(cross_section)
    spine_errors = validate_spine_rules(spine_df)
    if spine_errors:
        print(f"Error: spine validation failed ({len(spine_errors)} issue(s)):", file=sys.stderr)
        for err in spine_errors[:20]:
            print(f"  - {err}", file=sys.stderr)
        return 1
    spine_df.to_csv(spine_path, index=False)

    research_ticker = args.research_ticker.upper()
    if research_ticker in loaded:
        try:
            research_panel = load_panel(research_ticker)
            research_panel = filter_registry_complete(research_panel, research_ticker)
            research_spine = panel_to_spine(research_panel)
            research_out = company_artifact(research_ticker, "csv", "research_spine", "csv", mkdir=True)
            research_spine.to_csv(research_out, index=False)
            print(f"Wrote {research_out} ({len(research_spine)} rows, full {research_ticker} history)")
        except FileNotFoundError:
            print(f"  ! Skipping research spine: no panel for {research_ticker}", file=sys.stderr)

    stacked.to_csv(csv_path, index=False)

    xlsx_path = cross_company_artifact("workbooks", stem, "xlsx", mkdir=True)
    write_cross_section_panel_workbook(
        xlsx_path, stacked, spine_df, dimension_order=args.dimension_order
    )

    html_path.write_text(
        build_consolidated_html(
            stacked,
            lookups_by_ticker,
            tickers=loaded,
            period_buckets=period_buckets,
            default_bucket=default_bucket or "ALL",
            sector_label=sector,
            generated_at=summary["generated_at"],
            dimension_order=args.dimension_order,
        ),
        encoding="utf-8",
    )
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    coverage_path.write_text(json.dumps(coverage, indent=2), encoding="utf-8")

    print(f"Wrote {spine_path}")
    print(f"Wrote {html_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {coverage_path}")
    print(f"Wrote {csv_path}")
    print(f"Wrote {xlsx_path}")
    print(f"  {len(loaded)} ticker(s), {len(stacked)} rows, default bucket={default_bucket}")
    if skipped:
        print(f"  Skipped: {', '.join(skipped)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
