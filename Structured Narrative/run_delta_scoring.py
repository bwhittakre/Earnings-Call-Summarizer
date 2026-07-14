#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Focus 2 delta-scoring orchestrator (AMZN FY2024 pilot).
=======================================================

Builds the quarter-over-quarter narrative-change layer on top of the level
scores. For each CONSECUTIVE pair of quarters in output/AMZN_dimension_view.json:
  1. read the PRIOR quarter's structured summary as the baseline,
  2. fetch the CURRENT quarter's transcript through the swappable provider,
  3. ask the LLM what CHANGED per dimension (direction, magnitude, evidence),
  4. verify every change-excerpt against the current transcript (shared cascade),
  5. attach the deterministic numeric anchors (level delta, quant z delta).

Outputs (under output/):
  * AMZN_dimension_delta.{parquet,csv,xlsx}   long: one row per (transition, dimension)
  * AMZN_delta_view.json                       structured view for the HTML report
  * llm_audit/AMZN_{prior}_to_{current}_delta.json   raw LLM output for audit

The first quarter in the view has no prior, so no delta is produced for it.

    python "Structured Narrative/run_delta_scoring.py"
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

load_dotenv(HERE / ".env")
load_dotenv(REPO_ROOT / ".env")

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from output_paths import (  # noqa: E402
    company_artifact,
    company_layer,
    resolve_read_required,
)
from transcript_providers import get_provider, sync_inbox_transcripts, TranscriptNotFound  # noqa: E402
from dimension_scorer import ALL_DIMENSIONS, QUANT_COMPARABLE_DIMENSIONS  # noqa: E402
from delta_scorer import (  # noqa: E402
    DeltaScorer,
    format_prior_summary,
    CONTEXT_SUMMARY,
    CONTEXT_BOTH_TRANSCRIPTS,
    VALID_CONTEXTS,
)
from company_config import get_company  # noqa: E402
from quant_loader import load_quant_dim_z  # noqa: E402
from quarter_registry import mark_delta, ensure_registry, has_delta  # noqa: E402
from quarter_merge import (  # noqa: E402
    load_csv_rows,
    load_json_obj,
    merge_rows_by_period,
    merge_transitions,
    norm_quarters,
)

sys.path.insert(0, str(REPO_ROOT))
from src.llm.anthropic_client import AnthropicClient  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-6"


def parse_delta_context() -> str:
    raw = os.getenv("DELTA_CONTEXT", CONTEXT_SUMMARY).strip().lower()
    aliases = {
        "full": CONTEXT_BOTH_TRANSCRIPTS,
        "both": CONTEXT_BOTH_TRANSCRIPTS,
        "both_transcripts": CONTEXT_BOTH_TRANSCRIPTS,
        "full_transcripts": CONTEXT_BOTH_TRANSCRIPTS,
        "summary": CONTEXT_SUMMARY,
    }
    ctx = aliases.get(raw, raw)
    if ctx not in VALID_CONTEXTS:
        print(
            f"Warning: unknown DELTA_CONTEXT={raw!r}; using {CONTEXT_SUMMARY!r}.",
            file=sys.stderr,
        )
        return CONTEXT_SUMMARY
    return ctx


def _sign(x: float | None, eps: float = 1e-9) -> int | None:
    if x is None:
        return None
    if abs(x) < eps:
        return 0
    return 1 if x > 0 else -1


def _agrees(llm_mag: float, numeric_delta: float | None) -> bool | None:
    """True/False when both signals are directional; None when either is flat/absent."""
    ls, ns = _sign(llm_mag), _sign(numeric_delta)
    if ls in (None, 0) or ns in (None, 0):
        return None
    return ls == ns


def load_view(ticker: str) -> dict:
    view_file = resolve_read_required(ticker, "dimension_view", "json", layer="json")
    return json.loads(view_file.read_text(encoding="utf-8"))


def dim_maps(quarter: dict) -> dict[str, float | None]:
    """dimension -> level score for one view quarter."""
    scores: dict[str, float | None] = {}
    for d in quarter.get("dimensions", []):
        scores[d["dimension"]] = d.get("score")
    return scores


def write_outputs(ticker: str, rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    csv_path = company_artifact(ticker, "csv", "dimension_delta", "csv", mkdir=True)
    parquet_path = company_artifact(ticker, "parquet", "dimension_delta", "parquet", mkdir=True)
    df.to_csv(csv_path, index=False)
    try:
        df.to_parquet(parquet_path, index=False)
    except Exception as exc:
        print(f"  ! parquet write skipped: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Focus 2 delta scoring.")
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
        help="Re-score deltas ending in these fiscal periods and merge into existing outputs.",
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
        help="Re-score deltas even when the registry marks them complete.",
    )
    args = ap.parse_args()
    company = get_company(args.ticker, scope=args.scope)
    ticker = company.ticker
    rerun_periods = norm_quarters(args.quarters)
    extra_output = norm_quarters(args.extra_output_quarters)
    registry = ensure_registry(ticker)

    try:
        view = load_view(ticker)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    quarters = view.get("quarters", [])
    if len(quarters) < 2:
        print("Need at least two scored quarters to compute a delta.", file=sys.stderr)
        return 1

    transitions_to_score: list[tuple[dict, dict, str, str]] = []
    skipped_transitions: list[str] = []
    for i in range(1, len(quarters)):
        prior_q, current_q = quarters[i - 1], quarters[i]
        prior_period = prior_q["fiscal_period"]
        current_period = current_q["fiscal_period"]
        if not (company.is_output_quarter(current_period) or current_period in (extra_output or set())):
            continue
        if rerun_periods and current_period not in rerun_periods:
            continue
        if not args.force and has_delta(registry, current_period):
            skipped_transitions.append(f"{prior_period}->{current_period}")
            continue
        transitions_to_score.append((prior_q, current_q, prior_period, current_period))

    if skipped_transitions:
        print(
            f"Skipping {len(skipped_transitions)} transition(s) with existing delta scores: "
            f"{', '.join(skipped_transitions)}"
        )
    if not transitions_to_score:
        print("All transitions already have delta scores — nothing to do.")
        return 0

    scored_periods = {current for _, _, _, current in transitions_to_score}
    needs_merge = bool(skipped_transitions) or bool(rerun_periods)
    existing_delta_view = load_json_obj(ticker, "delta_view") if needs_merge else None
    delta_view_file = company_artifact(ticker, "json", "delta_view", "json", mkdir=True)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set (checked Structured Narrative/.env "
              "and repo-root .env).", file=sys.stderr)
        return 1

    model = os.getenv("DIMENSION_MODEL", DEFAULT_MODEL)
    delta_context = parse_delta_context()
    use_rescue = os.getenv("DIMENSION_RESCUE", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )
    sync_inbox_transcripts(ticker, verbose=True)
    try:
        provider = get_provider()
    except Exception as exc:
        print(f"Error initializing transcript provider: {exc}", file=sys.stderr)
        return 1

    client = AnthropicClient(api_key=api_key, model=model, max_retries=1)
    scorer = DeltaScorer(client, context=delta_context, use_rescue=use_rescue)
    audit_dir = company_layer(ticker, "audit", mkdir=True)

    print(f"Provider: {provider.name} | Model: {model} | delta context: {delta_context} "
          f"| paraphrase rescue: {'on' if use_rescue else 'off'}")
    print(f"Computing {len(transitions_to_score)} quarter-over-quarter transition(s) "
          f"across {len(ALL_DIMENSIONS)} dimensions.\n")

    rows: list[dict] = []
    transitions_view: list[dict] = []
    quant_z_by_fp = load_quant_dim_z(ticker)

    for prior_q, current_q, prior_period, current_period in transitions_to_score:
        print(f"[{prior_period} -> {current_period}] fetching transcripts…")
        try:
            prior_transcript = provider.fetch(ticker, prior_period)
            transcript = provider.fetch(ticker, current_period)
        except TranscriptNotFound as exc:
            print(f"  ! {exc}; skipping transition")
            continue

        # Local transcripts carry no call date; fall back to the level view's
        # as-of/earnings date so the report can still show when the call was.
        as_of = (
            transcript.call_date
            or current_q.get("as_of_date")
            or current_q.get("earnings_date")
        )
        prior_scores = dim_maps(prior_q)
        current_scores = dim_maps(current_q)
        prior_zs = quant_z_by_fp.get(str(prior_period), {})
        current_zs = quant_z_by_fp.get(str(current_period), {})
        prior_block = format_prior_summary(prior_q)

        print(f"[{prior_period} -> {current_period}] scoring narrative change…")
        if delta_context == CONTEXT_BOTH_TRANSCRIPTS:
            scored = scorer.score(
                transcript,
                prior_period,
                company.company_name,
                prior_transcript=prior_transcript,
            )
        else:
            scored = scorer.score(
                transcript,
                prior_period,
                company.company_name,
                prior_summary_block=prior_block,
            )

        status_counts: dict[str, int] = {}
        deltas_view: list[dict] = []
        for d in scored.deltas:
            dim = d.dimension
            ps, cs = prior_scores.get(dim), current_scores.get(dim)
            score_delta = (
                round(float(cs) - float(ps), 1)
                if isinstance(ps, (int, float)) and isinstance(cs, (int, float))
                else None
            )
            pz, cz = prior_zs.get(dim), current_zs.get(dim)
            quant_z_delta = (
                round(float(cz) - float(pz), 3)
                if d.is_quant_comparable
                and isinstance(pz, (int, float))
                and isinstance(cz, (int, float))
                else None
            )
            agrees = _agrees(d.change_magnitude, score_delta)
            quant_agrees = (
                _agrees(d.change_magnitude, quant_z_delta)
                if quant_z_delta is not None else None
            )

            for e in d.evidence:
                status_counts[e.status] = status_counts.get(e.status, 0) + 1

            rows.append({
                "ticker": ticker,
                "prior_period": prior_period,
                "fiscal_period": current_period,
                "as_of_date": as_of,
                "dimension": dim,
                "is_quant_comparable": d.is_quant_comparable,
                "prior_score": ps,
                "current_score": cs,
                "score_delta": score_delta,
                "change_direction": d.change_direction,
                "change_magnitude": d.change_magnitude,
                "agrees_with_numbers": agrees,
                "quant_z_prior": pz if d.is_quant_comparable else None,
                "quant_z_current": cz if d.is_quant_comparable else None,
                "quant_z_delta": quant_z_delta,
                "quant_agrees": quant_agrees,
                "rationale": d.rationale,
                "n_evidence": d.n_evidence,
                "n_evidence_verified": d.n_evidence_verified,
                "evidence_verified": d.evidence_verified,
                "excerpts": " || ".join(d.excerpts),
                "source": transcript.source_name,
                "delta_context": delta_context,
            })

            deltas_view.append({
                "dimension": dim,
                "is_quant_comparable": d.is_quant_comparable,
                "prior_score": ps,
                "current_score": cs,
                "score_delta": score_delta,
                "change_direction": d.change_direction,
                "change_magnitude": d.change_magnitude,
                "agrees_with_numbers": agrees,
                "quant_z_prior": pz if d.is_quant_comparable else None,
                "quant_z_current": cz if d.is_quant_comparable else None,
                "quant_z_delta": quant_z_delta,
                "quant_agrees": quant_agrees,
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
            })

        transitions_view.append({
            "prior_period": prior_period,
            "fiscal_period": current_period,
            "as_of_date": as_of,
            "source": transcript.source_name,
            "delta_context": delta_context,
            "n_chars_prior": len(prior_transcript.raw_text),
            "n_chars_current": len(transcript.raw_text),
            "n_speakers": transcript.n_speakers,
            "pct_verified": (
                round(100.0 * scored.n_excerpts_verified / scored.n_excerpts, 1)
                if scored.n_excerpts else None
            ),
            "deltas": deltas_view,
        })

        audit = {
            "delta_context": delta_context,
            "summary": scored.summary.model_dump(),
            "numeric_anchors": [
                {
                    "dimension": r["dimension"],
                    "score_delta": r["score_delta"],
                    "quant_z_delta": r["quant_z_delta"],
                    "agrees_with_numbers": r["agrees_with_numbers"],
                }
                for r in rows if r["fiscal_period"] == current_period
            ],
            "raw_response": scored.llm_result.raw_response,
        }
        (audit_dir / f"{prior_period}_to_{current_period}_delta.json").write_text(
            json.dumps(audit, indent=2), encoding="utf-8"
        )

        breakdown = " ".join(
            f"{k}={status_counts.get(k, 0)}"
            for k in ("verbatim", "composite", "anchored", "paraphrased", "unverified")
        )
        vpct = (100.0 * scored.n_excerpts_verified / scored.n_excerpts
                if scored.n_excerpts else 0.0)
        print(f"  {len(scored.deltas)} dims, "
              f"{scored.n_excerpts_verified}/{scored.n_excerpts} change-excerpts "
              f"supported ({vpct:.0f}%)  [{breakdown}]\n")

        mark_delta(ticker, current_period)

    if not rows:
        print("No transitions produced — nothing written.", file=sys.stderr)
        return 1

    if needs_merge:
        existing_rows = load_csv_rows(ticker, "dimension_delta")
        rows = merge_rows_by_period(existing_rows, rows, scored_periods)
        if existing_delta_view:
            transitions_view = merge_transitions(
                existing_delta_view.get("transitions", []),
                transitions_view,
                scored_periods,
            )
        elif skipped_transitions:
            print(
                "Warning: skipped transitions but delta_view missing — "
                "output may be incomplete.",
                file=sys.stderr,
            )
        if not rows:
            print("No transitions produced — nothing written.", file=sys.stderr)
            return 1

    write_outputs(ticker, rows)

    delta_view = {
        "ticker": ticker,
        "company_name": company.company_name,
        "model": model,
        "delta_context": delta_context,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimension_order": ALL_DIMENSIONS,
        "quant_comparable": QUANT_COMPARABLE_DIMENSIONS,
        "transitions": transitions_view,
    }
    delta_view_file.write_text(json.dumps(delta_view, indent=2), encoding="utf-8")

    print(client.usage_summary())
    print(f"\nWrote {len(rows)} delta rows to csv/dimension_delta")
    print(f"Delta view JSON: {delta_view_file}")
    print(f"LLM audit JSON:  {audit_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
