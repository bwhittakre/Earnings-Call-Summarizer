#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Focus 3 surprise-scoring orchestrator (AMZN FY2024 pilot).
==========================================================

For each quarter in output/AMZN_dimension_view.json:
  1. build a PIT consensus context block from the quant spine,
  2. fetch the earnings-call transcript,
  3. ask the LLM where management's narrative diverged from expectations,
  4. verify excerpts, attach quant z + agreement/gap flags.

Outputs (under output/):
  * AMZN_dimension_surprise.{csv,parquet,xlsx}
  * AMZN_surprise_view.json
  * llm_audit/AMZN_{fiscal_period}_surprise.json

    python "Structured Narrative/run_surprise_scoring.py"
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

from excel_export import build_narrative_layers_workbook  # noqa: E402
from output_paths import company_artifact, company_layer, resolve_read_required  # noqa: E402
from transcript_providers import get_provider, sync_inbox_transcripts, TranscriptNotFound  # noqa: E402
from dimension_scorer import ALL_DIMENSIONS, QUANT_COMPARABLE_DIMENSIONS  # noqa: E402
from consensus_context import (  # noqa: E402
    format_consensus_context,
    format_level_summary,
    try_load_quant_long,
)
from surprise_scorer import SurpriseScorer  # noqa: E402
from company_config import get_company  # noqa: E402
from quarter_merge import (  # noqa: E402
    load_json_obj,
    load_parquet_df,
    merge_dataframes_by_period,
    merge_quarter_views,
    merge_rows_by_period,
    norm_quarters,
)

sys.path.insert(0, str(REPO_ROOT))
from src.llm.anthropic_client import AnthropicClient  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-6"


def _sign(x: float | None, eps: float = 1e-9) -> int | None:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if abs(x) < eps:
        return 0
    return 1 if x > 0 else -1


def _agrees(surprise_mag: float, quant_z: float | None) -> bool | None:
    ls, qs = _sign(surprise_mag), _sign(quant_z)
    if ls in (None, 0) or qs in (None, 0):
        return None
    return ls == qs


def _narrative_quant_gap(surprise_mag: float, quant_z: float | None) -> float | None:
    """Simple gap: surprise magnitude minus quant z (clamped quant to [-2,2])."""
    if quant_z is None or (isinstance(quant_z, float) and pd.isna(quant_z)):
        return None
    q = max(-2.0, min(2.0, float(quant_z)))
    return round(float(surprise_mag) - q, 2)


def load_view(ticker: str) -> dict:
    view_file = resolve_read_required(ticker, "dimension_view", "json", layer="json")
    return json.loads(view_file.read_text(encoding="utf-8"))


from quant_loader import load_quant_dim_z  # noqa: E402
from pit_config import is_pit_mode  # noqa: E402
from quarter_registry import mark_surprise, ensure_registry, has_surprise  # noqa: E402


def dim_level_map(quarter: dict) -> dict[str, float | None]:
    return {
        d["dimension"]: d.get("score")
        for d in quarter.get("dimensions", [])
    }


def write_outputs(ticker: str, rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    parquet_path = company_artifact(ticker, "parquet", "dimension_surprise", "parquet", mkdir=True)
    try:
        df.to_parquet(parquet_path, index=False)
        print(f"Wrote {parquet_path}")
    except Exception as exc:
        print(f"  ! parquet write skipped: {exc}")
    try:
        workbook = build_narrative_layers_workbook(ticker)
        print(f"Wrote {workbook}")
    except Exception as exc:
        print(f"  ! narrative_layers workbook skipped: {exc}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Focus 3 surprise scoring.")
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
        help="Re-score surprise even when the registry marks quarters complete.",
    )
    args = ap.parse_args()
    company = get_company(args.ticker, scope=args.scope)
    ticker = company.ticker
    rerun_periods = norm_quarters(args.quarters)
    extra_output = norm_quarters(args.extra_output_quarters)
    registry = ensure_registry(ticker)

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        return 1

    try:
        view = load_view(ticker)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    quant_df = try_load_quant_long(ticker)
    if quant_df is None:
        print(
            f"Note: {ticker}_narrative_quant not found; surprise will run without "
            "consensus/quant context (agrees_with_quant and narrative_quant_gap will be null).",
            file=sys.stderr,
        )

    quarters = view.get("quarters", [])
    if not quarters:
        print("No quarters in dimension view.", file=sys.stderr)
        return 1

    quant_z_by_fp = load_quant_dim_z(ticker)

    scoped_output = [
        q for q in quarters
        if company.is_output_quarter(q["fiscal_period"]) or q["fiscal_period"] in (extra_output or set())
    ]
    if rerun_periods:
        scoped_output = [q for q in scoped_output if q["fiscal_period"] in rerun_periods]
    skipped = [
        q["fiscal_period"] for q in scoped_output
        if not args.force and has_surprise(registry, q["fiscal_period"])
    ]
    if skipped:
        print(
            f"Skipping {len(skipped)} quarter(s) with existing surprise scores: "
            f"{', '.join(skipped)}"
        )
    output_quarters = [
        q for q in scoped_output
        if args.force or not has_surprise(registry, q["fiscal_period"])
    ]

    if not output_quarters:
        print("All output quarters already have surprise scores — nothing to do.")
        return 0

    scored_periods = {q["fiscal_period"] for q in output_quarters}
    needs_merge = len(scored_periods) < len(scoped_output) or bool(rerun_periods)
    existing_surprise_view = load_json_obj(ticker, "surprise_view") if needs_merge else None
    surprise_view_file = company_artifact(ticker, "json", "surprise_view", "json", mkdir=True)

    model = os.getenv("DIMENSION_MODEL", DEFAULT_MODEL)
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
    scorer = SurpriseScorer(client, use_rescue=use_rescue)
    audit_dir = company_layer(ticker, "audit", mkdir=True)

    print(f"Provider: {provider.name} | Model: {model} | paraphrase rescue: "
          f"{'on' if use_rescue else 'off'}")
    print(f"Scoring narrative surprise for {len(output_quarters)} output quarter(s) "
          f"across {len(ALL_DIMENSIONS)} dimensions.\n")

    rows: list[dict] = []
    quarters_view: list[dict] = []

    for q in output_quarters:
        fp = q["fiscal_period"]
        print(f"[{fp}] fetching transcript…")
        try:
            transcript = provider.fetch(ticker, fp)
        except TranscriptNotFound as exc:
            print(f"  ! {exc}; skipping")
            continue

        as_of = (
            transcript.call_date
            or q.get("as_of_date")
            or q.get("earnings_date")
        )
        dim_z = quant_z_by_fp.get(fp, {})
        levels = dim_level_map(q)
        consensus_block = format_consensus_context(
            fp,
            quant_df,
            dim_z,
            ticker=ticker,
            include_validation_revisions=not is_pit_mode(),
        )
        level_block = format_level_summary(q)

        print(f"[{fp}] scoring narrative surprise…")
        scored = scorer.score(transcript, consensus_block, company.company_name, level_block)

        status_counts: dict[str, int] = {}
        surprises_view: list[dict] = []

        for s in scored.surprises:
            dim = s.dimension
            qz = dim_z.get(dim) if s.is_quant_comparable else None
            llm_level = levels.get(dim)
            agrees = _agrees(s.surprise_magnitude, qz) if s.is_quant_comparable else None
            gap = _narrative_quant_gap(s.surprise_magnitude, qz) if s.is_quant_comparable else None

            for e in s.evidence:
                status_counts[e.status] = status_counts.get(e.status, 0) + 1

            rows.append({
                "ticker": ticker,
                "fiscal_period": fp,
                "as_of_date": as_of,
                "dimension": dim,
                "is_quant_comparable": s.is_quant_comparable,
                "llm_level": llm_level,
                "quant_z": qz,
                "surprise_direction": s.surprise_direction,
                "surprise_magnitude": s.surprise_magnitude,
                "agrees_with_quant": agrees,
                "narrative_quant_gap": gap,
                "rationale": s.rationale,
                "n_evidence": s.n_evidence,
                "n_evidence_verified": s.n_evidence_verified,
                "evidence_verified": s.evidence_verified,
                "excerpts": " || ".join(s.excerpts),
                "source": transcript.source_name,
            })

            surprises_view.append({
                "dimension": dim,
                "is_quant_comparable": s.is_quant_comparable,
                "llm_level": llm_level,
                "quant_z": qz,
                "surprise_direction": s.surprise_direction,
                "surprise_magnitude": s.surprise_magnitude,
                "agrees_with_quant": agrees,
                "narrative_quant_gap": gap,
                "rationale": s.rationale,
                "evidence": [
                    {
                        "claim": e.claim,
                        "excerpt": e.excerpt,
                        "verified": e.verified,
                        "status": e.status,
                        "canonical": e.canonical,
                    }
                    for e in s.evidence
                ],
            })

        quarters_view.append({
            "fiscal_period": fp,
            "as_of_date": as_of,
            "source": transcript.source_name,
            "n_chars": len(transcript.raw_text),
            "pct_verified": (
                round(100.0 * scored.n_excerpts_verified / scored.n_excerpts, 1)
                if scored.n_excerpts else None
            ),
            "surprises": surprises_view,
        })

        audit = {
            "summary": scored.summary.model_dump(),
            "consensus_context_preview": consensus_block[:4000],
            "numeric_anchors": [
                {
                    "dimension": r["dimension"],
                    "quant_z": r["quant_z"],
                    "agrees_with_quant": r["agrees_with_quant"],
                    "narrative_quant_gap": r["narrative_quant_gap"],
                }
                for r in rows if r["fiscal_period"] == fp
            ],
            "raw_response": scored.llm_result.raw_response,
        }
        (audit_dir / f"{fp}_surprise.json").write_text(
            json.dumps(audit, indent=2), encoding="utf-8"
        )

        breakdown = " ".join(
            f"{k}={status_counts.get(k, 0)}"
            for k in ("verbatim", "composite", "anchored", "paraphrased", "unverified")
        )
        vpct = (100.0 * scored.n_excerpts_verified / scored.n_excerpts
                if scored.n_excerpts else 0.0)
        print(f"  {len(scored.surprises)} dims, "
              f"{scored.n_excerpts_verified}/{scored.n_excerpts} excerpts supported "
              f"({vpct:.0f}%)  [{breakdown}]\n")

        mark_surprise(ticker, fp)

    if not rows:
        print("No quarters scored.", file=sys.stderr)
        return 1

    if needs_merge:
        existing_df = load_parquet_df(ticker, "dimension_surprise")
        new_df = pd.DataFrame(rows)
        merged_df = merge_dataframes_by_period(existing_df, new_df, scored_periods)
        rows = merged_df.to_dict("records")
        if existing_surprise_view:
            quarters_view = merge_quarter_views(
                existing_surprise_view.get("quarters", []),
                quarters_view,
                scored_periods,
            )
        if not rows:
            print("No quarters scored.", file=sys.stderr)
            return 1

    write_outputs(ticker, rows)

    surprise_view = {
        "ticker": ticker,
        "company_name": company.company_name,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimension_order": ALL_DIMENSIONS,
        "quant_comparable": QUANT_COMPARABLE_DIMENSIONS,
        "quarters": quarters_view,
    }
    surprise_view_file.write_text(json.dumps(surprise_view, indent=2), encoding="utf-8")

    print(client.usage_summary())
    print(f"\nWrote {len(rows)} surprise rows to parquet/dimension_surprise")
    print(f"Surprise view JSON: {surprise_view_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
