#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AMZN FY2024 transcript dimension-scoring pilot — orchestrator.
==============================================================

For each of AMZN's FY2024 quarters:
  1. fetch the earnings-call transcript through the swappable provider layer,
  2. score it across business dimensions with the evidence-validated LLM stack,
  3. verify every excerpt back against the transcript.

Outputs (all under output/):
  * AMZN_llm_dimension_scores.{parquet,csv,xlsx}   long: one row per (quarter, dimension)
  * AMZN_dimension_view.json                        structured view for the HTML report
  * AMZN_transcript_coverage_FY2024.{csv,xlsx}     one row per quarter: coverage/quality
  * llm_audit/AMZN_{fiscal_period}_dimensions.json  raw LLM output for audit
  * transcripts/AMZN_{fiscal_period}.json           raw provider payload (cached)

Everything is keyed on `fiscal_period` (FY{YYYY}-Q{N}) so it lines up with the
quant spine in AMZN_dimension_scores.

    python "Structured Narrative/run_dimension_scoring.py"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

# Load both env files: FMP_API_KEY/TRANSCRIPT_PROVIDER live in the subproject
# .env; ANTHROPIC_API_KEY lives in the repo-root .env used by the main pipeline.
load_dotenv(HERE / ".env")
load_dotenv(REPO_ROOT / ".env")

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from output_paths import (  # noqa: E402
    company_artifact,
    company_layer,
    resolve_read_parquet_or_csv,
)
from transcript_providers import get_provider, sync_inbox_transcripts, TranscriptNotFound  # noqa: E402
from dimension_scorer import (  # noqa: E402
    DimensionScorer,
    ALL_DIMENSIONS,
    QUANT_COMPARABLE_DIMENSIONS,
)
from company_config import get_company  # noqa: E402
from quarter_registry import mark_dimensions, set_prior_only, ensure_registry, has_dimensions  # noqa: E402
from quarter_merge import (  # noqa: E402
    load_csv_rows,
    load_json_obj,
    merge_quarter_views,
    merge_rows_by_period,
    norm_quarters,
)
from quant_loader import load_quant_dim_z  # noqa: E402

sys.path.insert(0, str(REPO_ROOT))
from src.llm.anthropic_client import AnthropicClient  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-6"


def load_quant_earnings_dates(ticker: str) -> dict[str, pd.Timestamp]:
    quant_file = resolve_read_parquet_or_csv(ticker, "dimension_scores", layer="parquet")
    if quant_file is None:
        print("  ! dimension_scores not found; date-match check will be skipped.")
        return {}
    df = (
        pd.read_parquet(quant_file)
        if quant_file.suffix == ".parquet"
        else pd.read_csv(quant_file)
    )
    if "fiscal_period" not in df.columns or "earnings_date" not in df.columns:
        return {}
    df["earnings_date"] = pd.to_datetime(df["earnings_date"], errors="coerce")
    return dict(zip(df["fiscal_period"], df["earnings_date"]))


from quant_loader import load_quant_dim_z  # noqa: E402


def date_match(call_date: str | None, earnings_date) -> tuple[float | None, bool | None]:
    if not call_date or earnings_date is None or pd.isna(earnings_date):
        return None, None
    cd = pd.to_datetime(call_date, errors="coerce")
    if pd.isna(cd):
        return None, None
    days = abs((cd.normalize() - pd.Timestamp(earnings_date).normalize()).days)
    return float(days), days <= 3


def write_outputs(ticker: str, score_rows: list[dict], coverage_rows: list[dict]) -> None:
    scores_df = pd.DataFrame(score_rows)
    cov_df = pd.DataFrame(coverage_rows)

    scores_csv = company_artifact(ticker, "csv", "llm_dimension_scores", "csv", mkdir=True)
    cov_csv = company_artifact(ticker, "csv", "transcript_coverage", "csv", mkdir=True)
    scores_df.to_csv(scores_csv, index=False)
    cov_df.to_csv(cov_csv, index=False)

    scores_parquet = company_artifact(ticker, "parquet", "llm_dimension_scores", "parquet", mkdir=True)
    try:
        scores_df.to_parquet(scores_parquet, index=False)
    except Exception as exc:
        print(f"  ! parquet write skipped for llm_dimension_scores: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Focus 1 dimension scoring.")
    ap.add_argument("--ticker", default="AMZN", help="Ticker symbol.")
    ap.add_argument(
        "--scope",
        choices=("five_year",),
        help="Quarter scope preset (five_year: AMZN FY2019-Q2 prior, FY2019-Q3..FY2024-Q3 output).",
    )
    ap.add_argument(
        "--quarters",
        nargs="+",
        default=[],
        help="Re-score only these fiscal periods and merge into existing outputs.",
    )
    ap.add_argument(
        "--extra-output-quarters",
        nargs="+",
        default=[],
        help="Treat these fiscal periods as output scope even if not in company_config.",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-score quarters even when the registry marks them complete.",
    )
    args = ap.parse_args()
    company = get_company(args.ticker, scope=args.scope)
    ticker = company.ticker
    rerun_periods = norm_quarters(args.quarters)
    extra_output = norm_quarters(args.extra_output_quarters)
    quarters = company.scoring_quarters()
    if rerun_periods:
        quarters = list(rerun_periods)
        if not quarters:
            print(f"No matching quarters in {args.quarters}", file=sys.stderr)
            return 1

    registry = ensure_registry(ticker)
    to_score = [
        q for q in quarters
        if args.force or not has_dimensions(registry, q)
    ]
    skipped = [q for q in quarters if q not in to_score]
    if skipped:
        print(
            f"Skipping {len(skipped)} quarter(s) with existing dimension scores: "
            f"{', '.join(skipped)}"
        )
    if not to_score:
        print(f"All {len(quarters)} quarter(s) already have dimension scores — nothing to do.")
        return 0

    scored_periods = set(to_score)
    needs_merge = bool(skipped) or bool(rerun_periods)
    existing_view = load_json_obj(ticker, "dimension_view") if needs_merge else None
    view_file = company_artifact(ticker, "json", "dimension_view", "json", mkdir=True)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set (checked Structured Narrative/.env "
              "and repo-root .env).", file=sys.stderr)
        return 1

    model = os.getenv("DIMENSION_MODEL", DEFAULT_MODEL)
    sync_inbox_transcripts(ticker, verbose=True)
    try:
        provider = get_provider()
    except Exception as exc:
        print(f"Error initializing transcript provider: {exc}", file=sys.stderr)
        return 1

    use_rescue = os.getenv("DIMENSION_RESCUE", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )
    client = AnthropicClient(api_key=api_key, model=model, max_retries=1)
    scorer = DimensionScorer(client, use_rescue=use_rescue)
    quant_dates = load_quant_earnings_dates(ticker)
    quant_z = load_quant_dim_z(ticker)

    audit_dir = company_layer(ticker, "audit", mkdir=True)

    print(f"Provider: {provider.name} | Model: {model} | paraphrase rescue: "
          f"{'on' if use_rescue else 'off'}")
    print(f"Scoring {len(to_score)} {ticker} quarters "
          f"({len(company.output_quarters)} in output scope) "
          f"across {len(ALL_DIMENSIONS)} dimensions."
          f"{'  [partial re-run]' if needs_merge else ''}\n")

    score_rows: list[dict] = []
    coverage_rows: list[dict] = []
    view_quarters: list[dict] = []

    for fp in to_score:
        print(f"[{fp}] fetching transcript…")
        try:
            transcript = provider.fetch(ticker, fp)
        except TranscriptNotFound as exc:
            print(f"  ! {exc}")
            coverage_rows.append({
                "fiscal_period": fp, "fetched": False, "source": provider.name,
                "error": str(exc),
            })
            continue

        print(f"  fetched {len(transcript.raw_text):,} chars, "
              f"{transcript.n_speakers} speakers, qa_found={transcript.qa_found}")
        print(f"[{fp}] scoring dimensions…")
        scored = scorer.score(transcript, company.company_name)

        in_output = company.is_output_quarter(fp) or fp in (extra_output or set())
        if in_output:
            for d in scored.dimensions:
                score_rows.append({
                    "ticker": ticker,
                    "fiscal_period": fp,
                    "as_of_date": transcript.call_date,
                    "dimension": d.dimension,
                    "score": d.score,
                    "is_quant_comparable": d.is_quant_comparable,
                    "quant_z": (
                        quant_z.get(fp, {}).get(d.dimension)
                        if d.is_quant_comparable else None
                    ),
                    "rationale": d.rationale,
                    "n_evidence": d.n_evidence,
                    "n_evidence_verified": d.n_evidence_verified,
                    "evidence_verified": d.evidence_verified,
                    "excerpts": " || ".join(d.excerpts),
                    "source": transcript.source_name,
                })

        ed = quant_dates.get(fp)
        ed_str = ed.strftime("%Y-%m-%d") if ed is not None and pd.notna(ed) else None
        view_quarters.append({
            "fiscal_period": fp,
            "output_scope": in_output,
            "prior_only": not in_output,
            "as_of_date": transcript.call_date,
            "earnings_date": ed_str,
            "source": transcript.source_name,
            "n_chars": len(transcript.raw_text),
            "n_speakers": transcript.n_speakers,
            "pct_verified": (
                round(100.0 * scored.n_excerpts_verified / scored.n_excerpts, 1)
                if scored.n_excerpts else None
            ),
            "dimensions": [
                {
                    "dimension": d.dimension,
                    "score": d.score,
                    "is_quant_comparable": d.is_quant_comparable,
                    "quant_z": quant_z.get(fp, {}).get(d.dimension),
                    "rationale": d.rationale,
                    "evidence": [
                        {
                            "claim": e.claim,
                            "excerpt": e.excerpt,
                            "verified": e.verified,
                            "status": e.status,
                            "canonical": e.canonical,
                        }
                        for e in d.evidence
                    ],
                }
                for d in scored.dimensions
            ],
        })

        status_counts: dict[str, int] = {}
        for d in scored.dimensions:
            for e in d.evidence:
                status_counts[e.status] = status_counts.get(e.status, 0) + 1

        days_diff, matched = date_match(transcript.call_date, quant_dates.get(fp))
        cov = transcript.as_meta()
        cov.update({
            "fetched": True,
            "earnings_date_quant": quant_dates.get(fp),
            "call_vs_earnings_days": days_diff,
            "date_match": matched,
            "n_dims_scored": len(scored.dimensions),
            "n_excerpts": scored.n_excerpts,
            "n_excerpts_verified": scored.n_excerpts_verified,
            "pct_verified": (
                round(100.0 * scored.n_excerpts_verified / scored.n_excerpts, 1)
                if scored.n_excerpts else None
            ),
            "n_verbatim": status_counts.get("verbatim", 0),
            "n_composite": status_counts.get("composite", 0),
            "n_anchored": status_counts.get("anchored", 0),
            "n_paraphrased": status_counts.get("paraphrased", 0),
            "n_unverified": status_counts.get("unverified", 0),
            "input_tokens": scored.llm_result.usage.input_tokens,
            "output_tokens": scored.llm_result.usage.output_tokens,
        })
        if in_output:
            coverage_rows.append(cov)

        audit = {
            "summary": scored.summary.model_dump(),
            "verification": [
                {
                    "dimension": d.dimension,
                    "n_evidence": d.n_evidence,
                    "n_evidence_verified": d.n_evidence_verified,
                    "evidence_verified": d.evidence_verified,
                }
                for d in scored.dimensions
            ],
            "raw_response": scored.llm_result.raw_response,
        }
        (audit_dir / f"{fp}_dimensions.json").write_text(
            json.dumps(audit, indent=2), encoding="utf-8"
        )
        vpct = (100.0 * scored.n_excerpts_verified / scored.n_excerpts
                if scored.n_excerpts else 0.0)
        breakdown = (
            f"verbatim={status_counts.get('verbatim', 0)} "
            f"composite={status_counts.get('composite', 0)} "
            f"anchored={status_counts.get('anchored', 0)} "
            f"paraphrased={status_counts.get('paraphrased', 0)} "
            f"unverified={status_counts.get('unverified', 0)}"
        )
        print(f"  scored {len(scored.dimensions)} dims, "
              f"{scored.n_excerpts_verified}/{scored.n_excerpts} excerpts supported "
              f"({vpct:.0f}%)  [{breakdown}]\n")

        mark_dimensions(
            ticker,
            fp,
            model=model,
            as_of_date=transcript.call_date,
        )

    if not score_rows:
        print("No transcripts scored — nothing written.", file=sys.stderr)
        return 1

    if needs_merge:
        existing_scores = load_csv_rows(ticker, "llm_dimension_scores")
        existing_cov = load_csv_rows(ticker, "transcript_coverage")
        score_rows = merge_rows_by_period(existing_scores, score_rows, scored_periods)
        coverage_rows = merge_rows_by_period(existing_cov, coverage_rows, scored_periods)
        if existing_view:
            view_quarters = merge_quarter_views(
                existing_view.get("quarters", []), view_quarters, scored_periods
            )
        elif skipped:
            print(
                "Warning: skipped quarters but dimension_view missing — "
                "output may be incomplete.",
                file=sys.stderr,
            )
        if not score_rows:
            print("No transcripts scored — nothing written.", file=sys.stderr)
            return 1

    write_outputs(ticker, score_rows, coverage_rows)

    view = {
        "ticker": ticker,
        "company_name": company.company_name,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimension_order": ALL_DIMENSIONS,
        "quant_comparable": QUANT_COMPARABLE_DIMENSIONS,
        "quarters": view_quarters,
    }
    view_file.write_text(json.dumps(view, indent=2), encoding="utf-8")
    if not rerun_periods and not extra_output:
        set_prior_only(ticker, list(company.prior_quarters))
    elif extra_output:
        from quarter_registry import load_registry, save_registry

        reg = load_registry(ticker)
        prior = set(reg.get("prior_only_quarters", []))
        for q in extra_output:
            prior.discard(q)
        for q in company.prior_quarters:
            if q not in extra_output:
                prior.add(q)
        reg["prior_only_quarters"] = sorted(prior)
        save_registry(ticker, reg)

    print(client.usage_summary())
    print(f"\nWrote {len(score_rows)} dimension rows to csv/llm_dimension_scores")
    print(f"View JSON:       {view_file}")
    print(f"Coverage report: csv/transcript_coverage.csv")
    print(f"LLM audit JSON:  {audit_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
