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

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
OUT_DIR = HERE / "output"
AUDIT_DIR = OUT_DIR / "llm_audit"

# Load both env files: FMP_API_KEY/TRANSCRIPT_PROVIDER live in the subproject
# .env; ANTHROPIC_API_KEY lives in the repo-root .env used by the main pipeline.
load_dotenv(HERE / ".env")
load_dotenv(REPO_ROOT / ".env")

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from excel_export import write_excel  # noqa: E402
from transcript_providers import get_provider, TranscriptNotFound  # noqa: E402
from dimension_scorer import (  # noqa: E402
    DimensionScorer,
    ALL_DIMENSIONS,
    QUANT_COMPARABLE_DIMENSIONS,
)
from pilot_config import (  # noqa: E402
    TICKER,
    COMPANY_NAME,
    OUTPUT_QUARTERS,
    is_output_quarter,
    scoring_quarters,
)

sys.path.insert(0, str(REPO_ROOT))
from src.llm.anthropic_client import AnthropicClient  # noqa: E402

QUARTERS = scoring_quarters()
DEFAULT_MODEL = "claude-sonnet-4-6"
QUANT_FILE = OUT_DIR / "AMZN_dimension_scores.csv"
VIEW_FILE = OUT_DIR / "AMZN_dimension_view.json"


def load_quant_earnings_dates() -> dict[str, pd.Timestamp]:
    """fiscal_period -> earnings_date from the quant spine, for a date-match check."""
    if not QUANT_FILE.exists():
        print(f"  ! {QUANT_FILE.name} not found; date-match check will be skipped.")
        return {}
    df = pd.read_csv(QUANT_FILE)
    if "fiscal_period" not in df.columns or "earnings_date" not in df.columns:
        return {}
    df["earnings_date"] = pd.to_datetime(df["earnings_date"], errors="coerce")
    return dict(zip(df["fiscal_period"], df["earnings_date"]))


def load_quant_z() -> dict[str, dict[str, float]]:
    """fiscal_period -> {dimension -> quant z-score} for the comparable dimensions
    (columns dim_<x>_z in the quant spine)."""
    if not QUANT_FILE.exists():
        return {}
    df = pd.read_csv(QUANT_FILE)
    if "fiscal_period" not in df.columns:
        return {}
    out: dict[str, dict[str, float]] = {}
    for _, r in df.iterrows():
        vals: dict[str, float] = {}
        for dim in QUANT_COMPARABLE_DIMENSIONS:
            col = f"dim_{dim}_z"
            if col in df.columns and pd.notna(r[col]):
                vals[dim] = round(float(r[col]), 3)
        out[str(r["fiscal_period"])] = vals
    return out


def date_match(call_date: str | None, earnings_date) -> tuple[float | None, bool | None]:
    if not call_date or earnings_date is None or pd.isna(earnings_date):
        return None, None
    cd = pd.to_datetime(call_date, errors="coerce")
    if pd.isna(cd):
        return None, None
    days = abs((cd.normalize() - pd.Timestamp(earnings_date).normalize()).days)
    return float(days), days <= 3


def write_outputs(score_rows: list[dict], coverage_rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    scores_df = pd.DataFrame(score_rows)
    cov_df = pd.DataFrame(coverage_rows)

    scores_base = OUT_DIR / "AMZN_llm_dimension_scores"
    cov_base = OUT_DIR / "AMZN_transcript_coverage_FY2024"

    scores_df.to_csv(scores_base.with_suffix(".csv"), index=False)
    cov_df.to_csv(cov_base.with_suffix(".csv"), index=False)

    for df, base in ((scores_df, scores_base), (cov_df, cov_base)):
        try:
            df.to_parquet(base.with_suffix(".parquet"), index=False)
        except Exception as exc:  # pyarrow missing etc. — CSV/XLSX still written
            print(f"  ! parquet write skipped for {base.name}: {exc}")
        try:
            write_excel(df, str(base.with_suffix(".xlsx")))
        except Exception as exc:
            print(f"  ! xlsx write skipped for {base.name}: {exc}")


def main() -> int:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set (checked Structured Narrative/.env "
              "and repo-root .env).", file=sys.stderr)
        return 1

    model = os.getenv("DIMENSION_MODEL", DEFAULT_MODEL)
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
    quant_dates = load_quant_earnings_dates()
    quant_z = load_quant_z()

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Provider: {provider.name} | Model: {model} | paraphrase rescue: "
          f"{'on' if use_rescue else 'off'}")
    print(f"Scoring {len(QUARTERS)} AMZN quarters ({len(OUTPUT_QUARTERS)} in output scope) "
          f"across {len(ALL_DIMENSIONS)} dimensions.\n")

    score_rows: list[dict] = []
    coverage_rows: list[dict] = []
    view_quarters: list[dict] = []

    for fp in QUARTERS:
        print(f"[{fp}] fetching transcript…")
        try:
            transcript = provider.fetch(TICKER, fp)
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
        scored = scorer.score(transcript, COMPANY_NAME)

        in_output = is_output_quarter(fp)
        if in_output:
            for d in scored.dimensions:
                score_rows.append({
                    "ticker": TICKER,
                    "fiscal_period": fp,
                    "as_of_date": transcript.call_date,
                    "dimension": d.dimension,
                    "score": d.score,
                    "is_quant_comparable": d.is_quant_comparable,
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
        (AUDIT_DIR / f"{TICKER}_{fp}_dimensions.json").write_text(
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

    if not score_rows:
        print("No transcripts scored — nothing written.", file=sys.stderr)
        return 1

    write_outputs(score_rows, coverage_rows)

    view = {
        "ticker": TICKER,
        "company_name": COMPANY_NAME,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimension_order": ALL_DIMENSIONS,
        "quant_comparable": QUANT_COMPARABLE_DIMENSIONS,
        "quarters": view_quarters,
    }
    VIEW_FILE.write_text(json.dumps(view, indent=2), encoding="utf-8")

    print(client.usage_summary())
    print(f"\nWrote {len(score_rows)} dimension rows to "
          f"{OUT_DIR / 'AMZN_llm_dimension_scores.csv'}")
    print(f"View JSON:       {VIEW_FILE}")
    print(f"Coverage report: {OUT_DIR / 'AMZN_transcript_coverage_FY2024.csv'}")
    print(f"LLM audit JSON:  {AUDIT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
