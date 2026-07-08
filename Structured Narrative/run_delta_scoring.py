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
VIEW_FILE = OUT_DIR / "AMZN_dimension_view.json"
DELTA_VIEW_FILE = OUT_DIR / "AMZN_delta_view.json"

load_dotenv(HERE / ".env")
load_dotenv(REPO_ROOT / ".env")

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from excel_export import write_excel  # noqa: E402
from transcript_providers import get_provider, TranscriptNotFound  # noqa: E402
from dimension_scorer import ALL_DIMENSIONS, QUANT_COMPARABLE_DIMENSIONS  # noqa: E402
from delta_scorer import (  # noqa: E402
    DeltaScorer,
    format_prior_summary,
    CONTEXT_SUMMARY,
    CONTEXT_BOTH_TRANSCRIPTS,
    VALID_CONTEXTS,
)

sys.path.insert(0, str(REPO_ROOT))
from src.llm.anthropic_client import AnthropicClient  # noqa: E402

TICKER = "AMZN"
COMPANY_NAME = "Amazon.com, Inc."
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


def load_view() -> dict:
    if not VIEW_FILE.exists():
        raise FileNotFoundError(
            f"{VIEW_FILE} not found. Run run_dimension_scoring.py first."
        )
    return json.loads(VIEW_FILE.read_text(encoding="utf-8"))


def dim_maps(quarter: dict) -> tuple[dict[str, float | None], dict[str, float | None]]:
    """dimension -> level score, and dimension -> quant z, for one view quarter."""
    scores: dict[str, float | None] = {}
    zs: dict[str, float | None] = {}
    for d in quarter.get("dimensions", []):
        scores[d["dimension"]] = d.get("score")
        zs[d["dimension"]] = d.get("quant_z")
    return scores, zs


def write_outputs(rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    base = OUT_DIR / "AMZN_dimension_delta"
    df.to_csv(base.with_suffix(".csv"), index=False)
    try:
        df.to_parquet(base.with_suffix(".parquet"), index=False)
    except Exception as exc:
        print(f"  ! parquet write skipped: {exc}")
    try:
        write_excel(df, str(base.with_suffix(".xlsx")))
    except Exception as exc:
        print(f"  ! xlsx write skipped: {exc}")


def main() -> int:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set (checked Structured Narrative/.env "
              "and repo-root .env).", file=sys.stderr)
        return 1

    try:
        view = load_view()
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    quarters = view.get("quarters", [])
    if len(quarters) < 2:
        print("Need at least two scored quarters to compute a delta.", file=sys.stderr)
        return 1

    model = os.getenv("DIMENSION_MODEL", DEFAULT_MODEL)
    delta_context = parse_delta_context()
    use_rescue = os.getenv("DIMENSION_RESCUE", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )
    try:
        provider = get_provider()
    except Exception as exc:
        print(f"Error initializing transcript provider: {exc}", file=sys.stderr)
        return 1

    client = AnthropicClient(api_key=api_key, model=model, max_retries=1)
    scorer = DeltaScorer(client, context=delta_context, use_rescue=use_rescue)
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Provider: {provider.name} | Model: {model} | delta context: {delta_context} "
          f"| paraphrase rescue: {'on' if use_rescue else 'off'}")
    print(f"Computing {len(quarters) - 1} quarter-over-quarter transitions "
          f"across {len(ALL_DIMENSIONS)} dimensions.\n")

    rows: list[dict] = []
    transitions_view: list[dict] = []

    for i in range(1, len(quarters)):
        prior_q, current_q = quarters[i - 1], quarters[i]
        prior_period = prior_q["fiscal_period"]
        current_period = current_q["fiscal_period"]
        print(f"[{prior_period} -> {current_period}] fetching transcripts…")
        try:
            prior_transcript = provider.fetch(TICKER, prior_period)
            transcript = provider.fetch(TICKER, current_period)
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
        prior_scores, prior_zs = dim_maps(prior_q)
        current_scores, current_zs = dim_maps(current_q)
        prior_block = format_prior_summary(prior_q)

        print(f"[{prior_period} -> {current_period}] scoring narrative change…")
        if delta_context == CONTEXT_BOTH_TRANSCRIPTS:
            scored = scorer.score(
                transcript,
                prior_period,
                COMPANY_NAME,
                prior_transcript=prior_transcript,
            )
        else:
            scored = scorer.score(
                transcript,
                prior_period,
                COMPANY_NAME,
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
                "ticker": TICKER,
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
        (AUDIT_DIR / f"{TICKER}_{prior_period}_to_{current_period}_delta.json").write_text(
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

    if not rows:
        print("No transitions produced — nothing written.", file=sys.stderr)
        return 1

    write_outputs(rows)

    delta_view = {
        "ticker": TICKER,
        "company_name": COMPANY_NAME,
        "model": model,
        "delta_context": delta_context,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimension_order": ALL_DIMENSIONS,
        "quant_comparable": QUANT_COMPARABLE_DIMENSIONS,
        "transitions": transitions_view,
    }
    DELTA_VIEW_FILE.write_text(json.dumps(delta_view, indent=2), encoding="utf-8")

    print(client.usage_summary())
    print(f"\nWrote {len(rows)} delta rows to "
          f"{OUT_DIR / 'AMZN_dimension_delta.csv'}")
    print(f"Delta view JSON: {DELTA_VIEW_FILE}")
    print(f"LLM audit JSON:  {AUDIT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
