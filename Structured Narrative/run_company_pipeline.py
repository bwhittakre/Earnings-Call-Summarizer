#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Run the full Structured Narrative pipeline for one ticker.

    python "Structured Narrative/run_company_pipeline.py" --ticker AMZN --scope five_year
    python "Structured Narrative/run_company_pipeline.py" --ticker AMZN --new-quarter FY2024-Q4
    python "Structured Narrative/run_company_pipeline.py" --ticker MSFT --skip-llm
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
from fiscal_period_util import normalize_fiscal_period, prior_fiscal_period  # noqa: E402
from output_paths import ensure_company_tree, resolve_read, resolve_read_parquet_or_csv  # noqa: E402
from pit_config import apply_pit_env, is_pit_mode  # noqa: E402
from quarter_registry import (  # noqa: E402
    ensure_registry,
    is_quarter_complete,
)


def run_step(label: str, cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"\n=== {label} ===")
    print(" ".join(cmd))
    merged = apply_pit_env(env or os.environ.copy())
    merged.setdefault("TRANSCRIPT_PROVIDER", "local")
    subprocess.run(cmd, cwd=HERE.parent, check=True, env=merged)


def assert_pit_spine(ticker: str) -> None:
    path = resolve_read_parquet_or_csv(ticker, "dimension_scores", layer="parquet")
    if path is None:
        if not is_pit_mode():
            return
        print(
            f"Warning: dimension_scores missing for {ticker}; run quant spine before LLM scoring.",
            file=sys.stderr,
        )
        return
    import pandas as pd

    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    if "dim_demand_z" not in df.columns:
        raise RuntimeError(
            f"PIT mode requires dimension_scores with dim_*_z columns for {ticker}. "
            "Run narrative_zscore.py after single_company_extractor.py."
        )


def resolve_new_quarter_args(ticker: str, new_quarter: str, force: bool) -> list[str] | None:
    """Return --quarters args for incremental scoring, or None to skip LLM."""
    fp = normalize_fiscal_period(new_quarter)
    reg = ensure_registry(ticker)
    if is_quarter_complete(reg, fp) and not force:
        print(f"Quarter {fp} already complete in registry — skipping LLM (use --force to re-score).")
        return None

    prior = prior_fiscal_period(fp)
    quarters = [fp]
    if prior and prior not in reg.get("scored_quarters", {}):
        quarters.insert(0, prior)
        print(f"Prior quarter {prior} not in registry — will score it first for delta baseline.")
    return ["--quarters", *quarters]


def main() -> int:
    ap = argparse.ArgumentParser(description="Run quant + LLM pipeline for one ticker.")
    ap.add_argument("--ticker", required=True, help="Ticker symbol.")
    ap.add_argument("--skip-quant", action="store_true", help="Skip Snowflake quant spine.")
    ap.add_argument("--skip-llm", action="store_true", help="Skip LLM scoring steps.")
    ap.add_argument(
        "--scope",
        choices=("five_year",),
        help="Quarter scope preset (five_year: AMZN FY2019-Q2 prior, FY2019-Q3..FY2024-Q3 output).",
    )
    ap.add_argument(
        "--quarters",
        nargs="+",
        default=[],
        help="Re-score only these fiscal periods (e.g. FY2025-Q1 FY2025-Q2).",
    )
    ap.add_argument(
        "--new-quarter",
        metavar="FYyyyy-Qn",
        help="Score one new output quarter incrementally (uses quarter registry).",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-score even when quarter registry marks the quarter complete.",
    )
    ap.add_argument(
        "--no-pit",
        action="store_true",
        help="Disable PIT guardrails (post-call revisions, rescue judge).",
    )
    ap.add_argument(
        "--append-quarters",
        nargs="+",
        default=[],
        help="When refreshing quant, fetch/merge only these fiscal periods.",
    )
    args = ap.parse_args()
    ticker = args.ticker.upper()
    sn = str(HERE)

    if args.no_pit:
        os.environ["NARRATIVE_PIT"] = "0"
    elif "NARRATIVE_PIT" not in os.environ:
        os.environ["NARRATIVE_PIT"] = "1"

    quarter_args: list[str] = []
    if args.new_quarter:
        resolved = resolve_new_quarter_args(ticker, args.new_quarter, args.force)
        if resolved is None:
            args.skip_llm = True
        else:
            quarter_args = resolved
            quarter_args.extend(["--extra-output-quarters", normalize_fiscal_period(args.new_quarter)])
    elif args.quarters:
        quarter_args = ["--quarters", *args.quarters]

    scope_args = ["--scope", args.scope] if args.scope else []
    force_args = ["--force"] if args.force else []
    panel_args = [PY, f"{sn}/build_feature_panel.py", "--ticker", ticker, *scope_args]
    if args.new_quarter and not args.scope:
        panel_args.extend(["--from-registry"])

    ensure_company_tree(ticker)
    if args.scope == "five_year":
        print("Scope: five_year — AMZN transcripts from Structured Narrative/AMZN/")
        print("  prior-only: FY2019-Q2 | output: FY2019-Q3 .. FY2024-Q3")
    if is_pit_mode():
        print("PIT mode: ON (expanding quant z; post-call revisions omitted from surprise context)")
    print(f"Output tree ready: output/{ticker}/{{parquet,workbooks,csv,json,reports,audit}}")

    quant_cmd = [PY, f"{sn}/single_company_extractor.py", "--ticker", ticker]
    if args.append_quarters:
        quant_cmd.extend(["--append-quarters", *args.append_quarters])

    if not args.skip_quant:
        run_step("Quant extract", quant_cmd)
        run_step("Quant z-score", [PY, f"{sn}/narrative_zscore.py", "--ticker", ticker])

    if not args.skip_llm:
        ensure_registry(ticker)
        assert_pit_spine(ticker)
        if args.scope != "five_year":
            run_step(
                "Bridge inbox transcripts",
                [PY, f"{sn}/export_inbox_to_transcripts_raw.py", "--ticker", ticker],
            )
        run_step(
            "Focus 1 dimensions",
            [PY, f"{sn}/run_dimension_scoring.py", "--ticker", ticker, *scope_args, *force_args, *quarter_args],
        )
        run_step(
            "Focus 2 delta",
            [PY, f"{sn}/run_delta_scoring.py", "--ticker", ticker, *scope_args, *force_args, *quarter_args],
        )
        run_step(
            "Focus 3 surprise",
            [PY, f"{sn}/run_surprise_scoring.py", "--ticker", ticker, *scope_args, *force_args, *quarter_args],
        )
        run_step(
            "Focus 3b novelty",
            [PY, f"{sn}/run_novelty_scoring.py", "--ticker", ticker, *scope_args, *force_args, *quarter_args],
        )

    if resolve_read_parquet_or_csv(ticker, "dimension_scores", layer="parquet") is not None:
        run_step(
            "Refresh quant anchors",
            [PY, f"{sn}/refresh_quant_anchors.py", "--ticker", ticker],
        )

    run_step("Feature panel", panel_args)

    run_step(
        "Join validation",
        [PY, f"{sn}/validate_transcript_join.py", "--ticker", ticker, *scope_args],
    )
    run_step(
        "Panel quant validation",
        [PY, f"{sn}/validate_panel_quant.py", "--ticker", ticker],
    )
    print(f"\nDone: {ticker} pipeline complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
