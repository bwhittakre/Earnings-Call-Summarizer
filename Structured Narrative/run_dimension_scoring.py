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

`resolve_scope()`, `prepare_items()`, and `finalize_and_write()` below are also
called directly (per ticker) by `run_universe_batch.py`, which combines the
dimension-scoring items of several tickers into a single Anthropic Message
Batch instead of running this script once per ticker.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
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
    ScoredTranscript,
    ALL_DIMENSIONS,
    QUANT_COMPARABLE_DIMENSIONS,
)
from batch_scoring import run_batch  # noqa: E402
from company_config import CompanyProfile, get_company  # noqa: E402
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


@dataclass
class DimensionScope:
    """Everything `finalize_and_write()` needs about one ticker's dimension run,
    computed by `resolve_scope()` before any transcript is fetched or scored."""

    ticker: str
    company: CompanyProfile
    to_score: list[str]
    skipped: list[str]
    rerun_periods: set[str] | None
    extra_output: set[str] | None
    needs_merge: bool
    existing_view: dict | None
    view_file: Path
    scored_periods: set[str]
    audit_dir: Path
    quant_dates: dict[str, "pd.Timestamp"] = field(default_factory=dict)
    quant_z: dict = field(default_factory=dict)


def resolve_scope(ticker: str, args: argparse.Namespace) -> DimensionScope | None:
    """Resolve which quarters need dimension scoring for one ticker.

    Returns None when there is nothing to score and nothing to promote
    (already handling the --extra-output-quarters prior_only bookkeeping in
    that case). When nothing needs *fresh* scoring but an already-scored
    quarter newly added to --extra-output-quarters is still flagged
    prior_only in the view, returns a DimensionScope with an empty to_score
    so finalize_and_write() can promote it (flip flags, backfill CSV rows)
    without re-scoring. Raises ValueError for a bad --quarters argument.
    """
    company = get_company(ticker, scope=args.scope)
    ticker = company.ticker
    rerun_periods = norm_quarters(args.quarters)
    extra_output = norm_quarters(args.extra_output_quarters)
    quarters = company.scoring_quarters()
    if rerun_periods:
        quarters = list(rerun_periods)
        if not quarters:
            raise ValueError(f"No matching quarters in {args.quarters}")

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
        # A quarter can need *promotion* (prior-only -> output scope) even
        # when nothing needs fresh scoring: it was already dims-scored, then
        # later added to --extra-output-quarters. Detect that here so we can
        # route through finalize_and_write()'s promotion patch (flips
        # prior_only/output_scope and backfills CSV rows from cached data)
        # instead of only doing the top-level registry bookkeeping below,
        # which sync_registry_from_views() would otherwise silently re-undo
        # on the next call (see prior_only_quarters bug fix).
        promotable: set[str] = set()
        existing_view = None
        if extra_output:
            existing_view = load_json_obj(ticker, "dimension_view")
            if existing_view:
                prior_fps = {
                    q["fiscal_period"]
                    for q in existing_view.get("quarters", [])
                    if q.get("prior_only")
                }
                promotable = set(extra_output) & prior_fps
        if promotable:
            print(
                f"{len(promotable)} already-scored quarter(s) need promotion from "
                f"prior-only to output scope: {', '.join(sorted(promotable))}"
            )
            view_file = company_artifact(ticker, "json", "dimension_view", "json", mkdir=True)
            audit_dir = company_layer(ticker, "audit", mkdir=True)
            return DimensionScope(
                ticker=ticker,
                company=company,
                to_score=[],
                skipped=sorted(promotable),
                rerun_periods=rerun_periods,
                extra_output=extra_output,
                needs_merge=True,
                existing_view=existing_view,
                view_file=view_file,
                scored_periods=set(),
                audit_dir=audit_dir,
                quant_dates=load_quant_earnings_dates(ticker),
                quant_z=load_quant_dim_z(ticker),
            )
        # Nothing to promote either (already promoted, or no view on disk
        # yet) -- still honor --extra-output-quarters bookkeeping on the
        # registry's top-level field so backfills aren't stuck in prior_only.
        if extra_output:
            from quarter_registry import load_registry, save_registry

            reg = load_registry(ticker)
            prior = set(reg.get("prior_only_quarters", []))
            for q in extra_output:
                prior.discard(q)
            reg["prior_only_quarters"] = sorted(prior)
            save_registry(ticker, reg)
            print(f"Updated prior_only_quarters (removed output: {', '.join(sorted(extra_output))})")
        return None

    scored_periods = set(to_score)
    needs_merge = bool(skipped) or bool(rerun_periods)
    existing_view = load_json_obj(ticker, "dimension_view") if needs_merge else None
    view_file = company_artifact(ticker, "json", "dimension_view", "json", mkdir=True)
    audit_dir = company_layer(ticker, "audit", mkdir=True)

    return DimensionScope(
        ticker=ticker,
        company=company,
        to_score=to_score,
        skipped=skipped,
        rerun_periods=rerun_periods,
        extra_output=extra_output,
        needs_merge=needs_merge,
        existing_view=existing_view,
        view_file=view_file,
        scored_periods=scored_periods,
        audit_dir=audit_dir,
        quant_dates=load_quant_earnings_dates(ticker),
        quant_z=load_quant_dim_z(ticker),
    )


def prepare_items(scope: DimensionScope, provider) -> tuple[list[dict], list[dict]]:
    """Fetch transcripts for every quarter in scope.to_score.

    Returns (prepared, failed_coverage): `prepared` is one dict per fetchable
    quarter (keys: fp, transcript), in order; `failed_coverage` is one
    coverage row per quarter whose transcript could not be fetched.
    """
    prepared: list[dict] = []
    failed_coverage: list[dict] = []
    for fp in scope.to_score:
        print(f"[{fp}] fetching transcript…")
        try:
            transcript = provider.fetch(scope.ticker, fp)
        except TranscriptNotFound as exc:
            print(f"  ! {exc}")
            failed_coverage.append({
                "fiscal_period": fp, "fetched": False, "source": provider.name,
                "error": str(exc),
            })
            continue
        print(f"  fetched {len(transcript.raw_text):,} chars, "
              f"{transcript.n_speakers} speakers, qa_found={transcript.qa_found}")
        prepared.append({"fp": fp, "transcript": transcript})
    return prepared, failed_coverage


def finalize_and_write(
    ticker: str,
    company: CompanyProfile,
    scope: DimensionScope,
    prepared: list[dict],
    failed_coverage: list[dict],
    scored_by_fp: dict[str, ScoredTranscript],
    model: str,
) -> int:
    """Post-process scored quarters, merge with existing outputs, and write
    csv/json/registry. Returns the number of view_quarters entries written
    (0 means nothing was written at all — a genuine failure)."""
    score_rows: list[dict] = []
    coverage_rows: list[dict] = list(failed_coverage)
    view_quarters: list[dict] = []

    for p in prepared:
        fp = p["fp"]
        transcript = p["transcript"]
        scored = scored_by_fp[fp]

        in_output = company.is_output_quarter(fp) or fp in (scope.extra_output or set())
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
                        scope.quant_z.get(fp, {}).get(d.dimension)
                        if d.is_quant_comparable else None
                    ),
                    "rationale": d.rationale,
                    "n_evidence": d.n_evidence,
                    "n_evidence_verified": d.n_evidence_verified,
                    "evidence_verified": d.evidence_verified,
                    "excerpts": " || ".join(d.excerpts),
                    "source": transcript.source_name,
                })

        ed = scope.quant_dates.get(fp)
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
                    "quant_z": scope.quant_z.get(fp, {}).get(d.dimension),
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

        days_diff, matched = date_match(transcript.call_date, scope.quant_dates.get(fp))
        cov = transcript.as_meta()
        cov.update({
            "fetched": True,
            "earnings_date_quant": scope.quant_dates.get(fp),
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
        (scope.audit_dir / f"{fp}_dimensions.json").write_text(
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

    # A quarter that was previously scored as prior-only (dims-only baseline)
    # but is now in --extra-output-quarters gets *skipped* above (its
    # dimensions are already cached — no need to re-call the LLM), so it
    # never reaches the `for p in prepared` loop and never gets a fresh
    # view_quarters/score_rows entry. Left alone, its stale
    # prior_only=true/output_scope=false record in the existing view would
    # (a) never gain the dimension-score CSV rows a real output quarter
    # needs, and (b) keep re-adding itself to registry prior_only_quarters
    # forever via sync_registry_from_views, silently hiding it from
    # --from-registry panel builds. Patch it here using the dimension data
    # already on file — no re-scoring needed.
    promote = set(scope.skipped) & (scope.extra_output or set())
    if promote and scope.existing_view:
        existing_by_fp = {
            q["fiscal_period"]: q for q in scope.existing_view.get("quarters", [])
        }
        for fp in sorted(promote):
            vq = existing_by_fp.get(fp)
            if vq is None or not vq.get("prior_only"):
                continue
            vq = dict(vq)
            vq["output_scope"] = True
            vq["prior_only"] = False
            for d in vq.get("dimensions", []):
                evidence = d.get("evidence", [])
                score_rows.append({
                    "ticker": ticker,
                    "fiscal_period": fp,
                    "as_of_date": vq.get("as_of_date"),
                    "dimension": d["dimension"],
                    "score": d["score"],
                    "is_quant_comparable": d.get("is_quant_comparable"),
                    "quant_z": d.get("quant_z"),
                    "rationale": d.get("rationale"),
                    "n_evidence": len(evidence),
                    "n_evidence_verified": sum(1 for e in evidence if e.get("verified")),
                    "evidence_verified": (
                        all(e.get("verified") for e in evidence) if evidence else True
                    ),
                    "excerpts": " || ".join(e.get("excerpt", "") for e in evidence),
                    "source": vq.get("source"),
                })
            view_quarters.append(vq)
            scope.scored_periods.add(fp)
            print(
                f"  [{fp}] promoted prior-only -> output scope "
                "(dims already cached; backfilling CSV rows)."
            )

    if not view_quarters:
        print("No transcripts scored — nothing written.", file=sys.stderr)
        return 0

    if scope.needs_merge:
        existing_scores = load_csv_rows(ticker, "llm_dimension_scores")
        existing_cov = load_csv_rows(ticker, "transcript_coverage")
        score_rows = merge_rows_by_period(existing_scores, score_rows, scope.scored_periods)
        coverage_rows = merge_rows_by_period(existing_cov, coverage_rows, scope.scored_periods)
        if scope.existing_view:
            view_quarters = merge_quarter_views(
                scope.existing_view.get("quarters", []), view_quarters, scope.scored_periods
            )
        elif scope.skipped:
            print(
                "Warning: skipped quarters but dimension_view missing — "
                "output may be incomplete.",
                file=sys.stderr,
            )

    # A run that only backfilled prior-only quarter(s) (no output-scope rows)
    # must still write dimension_view.json below (so future delta/novelty runs
    # see the baseline) — but there is nothing new for the CSV, and writing an
    # empty/partial frame here would clobber any existing output-scope history
    # on disk. Skip the CSV write in that case rather than treating it as an error.
    if score_rows:
        write_outputs(ticker, score_rows, coverage_rows)
    else:
        print("No output-scope rows this run (prior-only backfill) — csv/llm_dimension_scores left unchanged.")

    view = {
        "ticker": ticker,
        "company_name": company.company_name,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimension_order": ALL_DIMENSIONS,
        "quant_comparable": QUANT_COMPARABLE_DIMENSIONS,
        "quarters": view_quarters,
    }
    scope.view_file.write_text(json.dumps(view, indent=2), encoding="utf-8")
    if not scope.rerun_periods and not scope.extra_output:
        set_prior_only(ticker, list(company.prior_quarters))
    elif scope.extra_output:
        from quarter_registry import load_registry, save_registry

        reg = load_registry(ticker)
        prior = set(reg.get("prior_only_quarters", []))
        for q in scope.extra_output:
            prior.discard(q)
        for q in company.prior_quarters:
            if q not in scope.extra_output:
                prior.add(q)
        reg["prior_only_quarters"] = sorted(prior)
        save_registry(ticker, reg)

    print(f"\nWrote {len(score_rows)} dimension rows to csv/llm_dimension_scores")
    print(f"View JSON:       {scope.view_file}")
    print(f"Coverage report: csv/transcript_coverage.csv")
    print(f"LLM audit JSON:  {scope.audit_dir}")
    return len(view_quarters)


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
    ap.add_argument(
        "--batch",
        action="store_true",
        help="Submit dimension-scoring calls as one Anthropic Message Batch "
        "(~50%% cheaper than synchronous calls; async, can take minutes to "
        "~24h). Any item that errors in the batch is retried synchronously.",
    )
    ap.add_argument(
        "--batch-poll-interval",
        type=float,
        default=30.0,
        help="Seconds between batch status polls (--batch only).",
    )
    ap.add_argument(
        "--batch-timeout",
        type=float,
        default=None,
        help="Max seconds to wait for the batch before raising (--batch only; "
        "default: no timeout, up to Anthropic's 24h SLA).",
    )
    args = ap.parse_args()

    try:
        scope = resolve_scope(args.ticker, args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if scope is None:
        return 0
    ticker = scope.ticker
    company = scope.company

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

    print(f"Provider: {provider.name} | Model: {model} | paraphrase rescue: "
          f"{'on' if use_rescue else 'off'}")
    print(f"Scoring {len(scope.to_score)} {ticker} quarters "
          f"({len(company.output_quarters)} in output scope) "
          f"across {len(ALL_DIMENSIONS)} dimensions."
          f"{'  [partial re-run]' if scope.needs_merge else ''}\n")

    prepared, failed_coverage = prepare_items(scope, provider)

    scored_by_fp: dict[str, ScoredTranscript] = {}
    if args.batch and prepared:
        by_fp = {p["fp"]: p for p in prepared}
        items = [scorer.build_request(p["transcript"], company.company_name) for p in prepared]
        id_to_fp = {item.custom_id: p["fp"] for item, p in zip(items, prepared)}
        outcomes = run_batch(
            client, items, scorer.RESPONSE_MODEL,
            poll_interval=args.batch_poll_interval, timeout=args.batch_timeout,
        )
        retry_periods: list[str] = []
        for item in items:
            fp = id_to_fp[item.custom_id]
            outcome = outcomes.get(item.custom_id)
            if outcome is None or not outcome.ok:
                print(f"  ! [{fp}] batch item failed ({outcome.error if outcome else 'missing'}) "
                      "— will retry synchronously")
                retry_periods.append(fp)
                continue
            transcript = by_fp[fp]["transcript"]
            scored_by_fp[fp] = scorer.finalize(
                outcome.parsed, outcome.llm_result, item.custom_id, transcript.raw_text
            )
        for fp in retry_periods:
            transcript = by_fp[fp]["transcript"]
            print(f"[{fp}] scoring dimensions (sync retry)…")
            scored_by_fp[fp] = scorer.score(transcript, company.company_name)
    else:
        for p in prepared:
            print(f"[{p['fp']}] scoring dimensions…")
            scored_by_fp[p["fp"]] = scorer.score(p["transcript"], company.company_name)

    n_written = finalize_and_write(ticker, company, scope, prepared, failed_coverage, scored_by_fp, model)
    print(client.usage_summary())
    return 0 if n_written else 1


if __name__ == "__main__":
    raise SystemExit(main())
