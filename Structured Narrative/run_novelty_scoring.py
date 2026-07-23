#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Focus 3b: narrative NOVELTY scoring orchestrator for dimensions without
consensus comparison.

    python "Structured Narrative/run_novelty_scoring.py" --ticker AMZN

`resolve_scope()`, `prepare_items()`, and `finalize_and_write()` below are also
called directly (per ticker) by `run_universe_batch.py`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
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

from company_config import CompanyProfile, get_company  # noqa: E402
from delta_scorer import format_prior_summary  # noqa: E402
from dimension_scorer import NARRATIVE_ONLY_DIMENSIONS  # noqa: E402
from fiscal_period_util import prior_fiscal_period  # noqa: E402
from novelty_scorer import NoveltyScorer, ScoredNoveltyTranscript  # noqa: E402
from batch_scoring import run_batch  # noqa: E402
from output_paths import company_artifact, company_layer, resolve_read_required  # noqa: E402
from quarter_merge import (  # noqa: E402
    load_json_obj,
    load_parquet_df,
    merge_dataframes_by_period,
    merge_quarter_views,
    norm_quarters,
)
from quarter_registry import ensure_registry, has_novelty, mark_novelty  # noqa: E402
from transcript_providers import TranscriptNotFound, get_provider, sync_inbox_transcripts  # noqa: E402

sys.path.insert(0, str(REPO_ROOT))
from src.llm.anthropic_client import AnthropicClient  # noqa: E402

DEFAULT_MODEL = "claude-sonnet-4-6"


def load_view(ticker: str) -> dict:
    view_file = resolve_read_required(ticker, "dimension_view", "json", layer="json")
    return json.loads(view_file.read_text(encoding="utf-8"))


def write_outputs(ticker: str, rows: list[dict]) -> None:
    df = pd.DataFrame(rows)
    parquet_path = company_artifact(ticker, "parquet", "dimension_novelty", "parquet", mkdir=True)
    csv_path = company_artifact(ticker, "csv", "dimension_novelty", "csv", mkdir=True)
    df.to_csv(csv_path, index=False)
    try:
        df.to_parquet(parquet_path, index=False)
        print(f"Wrote {parquet_path}")
    except Exception as exc:
        print(f"  ! parquet write skipped: {exc}")


@dataclass
class NoveltyScope:
    """Everything `finalize_and_write()` needs about one ticker's novelty run,
    computed by `resolve_scope()` before any transcript is fetched or scored."""

    ticker: str
    company: CompanyProfile
    output_quarters: list[dict]
    q_by_fp: dict[str, dict]
    skipped: list[str]
    needs_merge: bool
    existing_view: dict | None
    novelty_view_file: Path
    scored_periods: set[str]
    audit_dir: Path


def resolve_scope(ticker: str, args: argparse.Namespace) -> NoveltyScope | None:
    """Resolve which quarters need novelty scoring for one ticker.

    Returns None when there is nothing to score. Raises FileNotFoundError if
    dimension_view.json is missing, or ValueError if it has no quarters.
    """
    company = get_company(ticker, scope=args.scope)
    ticker = company.ticker
    rerun_periods = norm_quarters(args.quarters)
    extra_output = norm_quarters(args.extra_output_quarters)
    registry = ensure_registry(ticker)

    view = load_view(ticker)
    quarters = view.get("quarters", [])
    if not quarters:
        raise ValueError("No quarters in dimension view.")

    q_by_fp = {q["fiscal_period"]: q for q in quarters}
    scoped_output = [
        q for q in quarters
        if company.is_output_quarter(q["fiscal_period"]) or q["fiscal_period"] in (extra_output or set())
    ]
    if rerun_periods:
        scoped_output = [q for q in scoped_output if q["fiscal_period"] in rerun_periods]
    skipped = [
        q["fiscal_period"] for q in scoped_output
        if not args.force and has_novelty(registry, q["fiscal_period"])
    ]
    if skipped:
        print(f"Skipping {len(skipped)} quarter(s) with existing novelty scores: {', '.join(skipped)}")
    output_quarters = [
        q for q in scoped_output
        if args.force or not has_novelty(registry, q["fiscal_period"])
    ]
    if not output_quarters:
        print("All output quarters already have novelty scores — nothing to do.")
        return None

    scored_periods = {q["fiscal_period"] for q in output_quarters}
    needs_merge = len(scored_periods) < len(scoped_output) or bool(rerun_periods)
    existing_view = load_json_obj(ticker, "novelty_view") if needs_merge else None
    novelty_view_file = company_artifact(ticker, "json", "novelty_view", "json", mkdir=True)
    audit_dir = company_layer(ticker, "audit", mkdir=True)

    return NoveltyScope(
        ticker=ticker,
        company=company,
        output_quarters=output_quarters,
        q_by_fp=q_by_fp,
        skipped=skipped,
        needs_merge=needs_merge,
        existing_view=existing_view,
        novelty_view_file=novelty_view_file,
        scored_periods=scored_periods,
        audit_dir=audit_dir,
    )


def prepare_items(scope: NoveltyScope, provider) -> list[dict]:
    """Fetch transcripts for every quarter in scope.output_quarters (skipping
    any quarter with no prior quarter in the view)."""
    prepared: list[dict] = []
    for q in scope.output_quarters:
        fp = q["fiscal_period"]
        prior_fp = prior_fiscal_period(fp)
        prior_q = scope.q_by_fp.get(prior_fp) if prior_fp else None
        if prior_q is None:
            print(f"[{fp}] ! no prior quarter in view; skipping novelty")
            continue

        print(f"[{fp}] fetching transcript…")
        try:
            transcript = provider.fetch(scope.ticker, fp)
        except TranscriptNotFound as exc:
            print(f"  ! {exc}; skipping")
            continue

        as_of = transcript.call_date or q.get("as_of_date") or q.get("earnings_date")
        prior_block = format_prior_summary(prior_q)
        prepared.append({
            "fp": fp, "prior_fp": prior_fp, "transcript": transcript,
            "as_of": as_of, "prior_block": prior_block,
        })
    return prepared


def finalize_and_write(
    ticker: str,
    company: CompanyProfile,
    scope: NoveltyScope,
    prepared: list[dict],
    scored_by_fp: dict[str, ScoredNoveltyTranscript],
    model: str,
) -> int:
    """Post-process scored quarters, merge with existing outputs, and write
    csv/json. Returns the number of rows written (0 means nothing was written
    at all)."""
    rows: list[dict] = []
    quarters_view: list[dict] = []

    for p in prepared:
        fp, prior_fp, transcript, as_of = p["fp"], p["prior_fp"], p["transcript"], p["as_of"]
        scored = scored_by_fp[fp]

        novelties_view: list[dict] = []
        for n in scored.novelties:
            rows.append({
                "ticker": ticker,
                "fiscal_period": fp,
                "as_of_date": as_of,
                "dimension": n.dimension,
                "novelty_direction": n.novelty_direction,
                "novelty_magnitude": n.novelty_magnitude,
                "rationale": n.rationale,
                "n_evidence": n.n_evidence,
                "n_evidence_verified": n.n_evidence_verified,
                "evidence_verified": n.evidence_verified,
                "excerpts": " || ".join(n.excerpts),
                "source": transcript.source_name,
            })
            novelties_view.append({
                "dimension": n.dimension,
                "novelty_direction": n.novelty_direction,
                "novelty_magnitude": n.novelty_magnitude,
                "rationale": n.rationale,
                "evidence": [
                    {"claim": e.claim, "excerpt": e.excerpt, "verified": e.verified, "status": e.status}
                    for e in n.evidence
                ],
            })

        quarters_view.append({
            "fiscal_period": fp,
            "prior_period": prior_fp,
            "as_of_date": as_of,
            "source": transcript.source_name,
            "novelties": novelties_view,
        })
        (scope.audit_dir / f"{fp}_novelty.json").write_text(
            json.dumps({"summary": scored.summary.model_dump()}, indent=2),
            encoding="utf-8",
        )
        mark_novelty(ticker, fp)
        print(f"  {len(scored.novelties)} dims scored\n")

    if not rows:
        print("No quarters scored.", file=sys.stderr)
        return 0

    if scope.needs_merge:
        existing_df = load_parquet_df(ticker, "dimension_novelty")
        merged_df = merge_dataframes_by_period(existing_df, pd.DataFrame(rows), scope.scored_periods)
        rows = merged_df.to_dict("records")
        if scope.existing_view:
            quarters_view = merge_quarter_views(
                scope.existing_view.get("quarters", []),
                quarters_view,
                scope.scored_periods,
            )

    write_outputs(ticker, rows)
    novelty_view = {
        "ticker": ticker,
        "company_name": company.company_name,
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "dimension_order": NARRATIVE_ONLY_DIMENSIONS,
        "quarters": quarters_view,
    }
    scope.novelty_view_file.write_text(json.dumps(novelty_view, indent=2), encoding="utf-8")

    print(f"\nWrote {len(rows)} novelty rows")
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Focus 3b novelty scoring.")
    ap.add_argument("--ticker", default="AMZN")
    ap.add_argument("--scope", choices=("five_year",))
    ap.add_argument("--quarters", nargs="+", default=[])
    ap.add_argument("--extra-output-quarters", nargs="+", default=[])
    ap.add_argument("--force", action="store_true")
    ap.add_argument(
        "--batch",
        action="store_true",
        help="Submit novelty-scoring calls as one Anthropic Message Batch "
        "(~50%% cheaper than synchronous calls; async, can take minutes to "
        "~24h). Any item that errors in the batch is retried synchronously.",
    )
    ap.add_argument("--batch-poll-interval", type=float, default=30.0)
    ap.add_argument("--batch-timeout", type=float, default=None)
    args = ap.parse_args()

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        return 1

    try:
        scope = resolve_scope(args.ticker, args)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if scope is None:
        return 0
    ticker = scope.ticker
    company = scope.company

    model = os.getenv("DIMENSION_MODEL", DEFAULT_MODEL)
    use_rescue = os.getenv("DIMENSION_RESCUE", "1").strip().lower() not in ("0", "false", "no", "off")
    sync_inbox_transcripts(ticker, verbose=True)
    provider = get_provider()
    client = AnthropicClient(api_key=api_key, model=model, max_retries=1)
    scorer = NoveltyScorer(client, use_rescue=use_rescue)

    print(f"Scoring narrative novelty for {len(scope.output_quarters)} quarter(s) "
          f"across {len(NARRATIVE_ONLY_DIMENSIONS)} dimensions.\n")

    prepared = prepare_items(scope, provider)

    scored_by_fp: dict[str, ScoredNoveltyTranscript] = {}
    if args.batch and prepared:
        items = [
            scorer.build_request(p["transcript"], p["prior_block"], company.company_name)
            for p in prepared
        ]
        by_fp = {p["fp"]: p for p in prepared}
        id_to_fp = {item.custom_id: p["fp"] for item, p in zip(items, prepared)}
        outcomes = run_batch(
            client, items, scorer.RESPONSE_MODEL,
            poll_interval=args.batch_poll_interval, timeout=args.batch_timeout,
        )
        retry_fps: list[str] = []
        for item in items:
            fp = id_to_fp[item.custom_id]
            outcome = outcomes.get(item.custom_id)
            if outcome is None or not outcome.ok:
                print(f"  ! [{fp}] batch item failed "
                      f"({outcome.error if outcome else 'missing'}) — will retry synchronously")
                retry_fps.append(fp)
                continue
            p = by_fp[fp]
            scored_by_fp[fp] = scorer.finalize(
                outcome.parsed, outcome.llm_result, item.custom_id, p["transcript"].raw_text
            )
        for fp in retry_fps:
            p = by_fp[fp]
            print(f"[{fp}] scoring narrative novelty (sync retry)…")
            scored_by_fp[fp] = scorer.score(p["transcript"], p["prior_block"], company.company_name)
    else:
        for p in prepared:
            print(f"[{p['fp']}] scoring narrative novelty…")
            scored_by_fp[p["fp"]] = scorer.score(p["transcript"], p["prior_block"], company.company_name)

    n_written = finalize_and_write(ticker, company, scope, prepared, scored_by_fp, model)
    print(client.usage_summary())
    return 0 if n_written else 1


if __name__ == "__main__":
    raise SystemExit(main())
