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
OUT_DIR = HERE / "output"
AUDIT_DIR = OUT_DIR / "llm_audit"

load_dotenv(HERE / ".env")
load_dotenv(REPO_ROOT / ".env")

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from excel_export import write_excel  # noqa: E402
from transcript_providers import get_provider, sync_inbox_transcripts, TranscriptNotFound  # noqa: E402
from dimension_scorer import ALL_DIMENSIONS, QUANT_COMPARABLE_DIMENSIONS  # noqa: E402
from consensus_context import (  # noqa: E402
    format_consensus_context,
    format_level_summary,
    try_load_quant_long,
)
from surprise_scorer import SurpriseScorer  # noqa: E402
from company_config import get_company  # noqa: E402

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
    view_file = OUT_DIR / f"{ticker}_dimension_view.json"
    if not view_file.exists():
        raise FileNotFoundError(
            f"{view_file} not found. Run run_dimension_scoring.py --ticker {ticker} first."
        )
    return json.loads(view_file.read_text(encoding="utf-8"))


def load_quant_dim_z(ticker: str) -> dict[str, dict[str, float | None]]:
    quant_dim_file = OUT_DIR / f"{ticker}_dimension_scores.csv"
    if not quant_dim_file.exists():
        return {}
    df = pd.read_csv(quant_dim_file)
    out: dict[str, dict[str, float | None]] = {}
    for _, r in df.iterrows():
        fp = str(r["fiscal_period"])
        vals: dict[str, float | None] = {}
        for dim in QUANT_COMPARABLE_DIMENSIONS:
            col = f"dim_{dim}_z"
            vals[dim] = float(r[col]) if col in df.columns and pd.notna(r[col]) else None
        out[fp] = vals
    return out


def dim_level_map(quarter: dict) -> dict[str, float | None]:
    return {
        d["dimension"]: d.get("score")
        for d in quarter.get("dimensions", [])
    }


def write_outputs(ticker: str, rows: list[dict]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    base = OUT_DIR / f"{ticker}_dimension_surprise"
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
    ap = argparse.ArgumentParser(description="Run Focus 3 surprise scoring.")
    ap.add_argument("--ticker", default="AMZN", help="Ticker symbol.")
    args = ap.parse_args()
    company = get_company(args.ticker)
    ticker = company.ticker
    surprise_view_file = OUT_DIR / f"{ticker}_surprise_view.json"

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
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Provider: {provider.name} | Model: {model} | paraphrase rescue: "
          f"{'on' if use_rescue else 'off'}")
    output_quarters = [q for q in quarters if company.is_output_quarter(q["fiscal_period"])]
    print(f"Scoring narrative surprise for {len(output_quarters)} output quarters "
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
        consensus_block = format_consensus_context(fp, quant_df, dim_z, ticker=ticker)
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
        (AUDIT_DIR / f"{ticker}_{fp}_surprise.json").write_text(
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
    print(f"\nWrote {len(rows)} surprise rows to "
          f"{OUT_DIR / f'{ticker}_dimension_surprise.csv'}")
    print(f"Surprise view JSON: {surprise_view_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
