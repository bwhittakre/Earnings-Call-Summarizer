#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cross-ticker batch orchestrator for the 4 LLM scoring stages.
===============================================================

Combines the dimension/delta/surprise/novelty scoring items of several
tickers into the minimum number of Anthropic Message Batches allowed by the
real data dependencies between stages:

  * delta, surprise, and novelty each only read `dimension_view.json`
    (never each other's outputs), so they have no dependency on one another.
  * dimensions must finish and be written to disk before delta/surprise/
    novelty run for that ticker.

So a run across N tickers submits exactly 2 batches (not up to 4*N):

  1. **Batch group 1** — dimension-scoring items for every ticker that needs
     it, submitted together as one Message Batch.
  2. **Batch group 2** — delta + surprise + novelty items for every ticker
     that needs them, submitted TOGETHER as one Message Batch (each item's
     own response model is tracked so `run_batch()` parses it correctly).

Every scorer's `build_request()` already sets
`custom_id = f"{ticker}_{fiscal_period}_{stage}"`, which is collision-free
across both ticker and stage, so items from different tickers/stages can
safely share one batch's custom_id space.

This script only covers the 4 LLM scoring stages. Quant extraction, feature-
panel building, and join/quant validation are not LLM-batched and stay
per-ticker via `run_company_pipeline.py --skip-llm` (or run individually).

Examples:

    python "Structured Narrative/run_universe_batch.py" --tickers AMZN MSFT NVDA AAPL --new-quarter FY2025-Q3
    python "Structured Narrative/run_universe_batch.py" --tickers MSFT NVDA AAPL --quarters FY2021-Q1 FY2021-Q2 --extra-output-quarters FY2021-Q2 --force
    python "Structured Narrative/run_universe_batch.py" --tickers AMZN MSFT --stages delta surprise novelty
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent

load_dotenv(HERE / ".env")
load_dotenv(REPO_ROOT / ".env")

if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import run_dimension_scoring as dim_mod  # noqa: E402
import run_delta_scoring as delta_mod  # noqa: E402
import run_surprise_scoring as surprise_mod  # noqa: E402
import run_novelty_scoring as novelty_mod  # noqa: E402
from batch_scoring import run_batch  # noqa: E402
from company_config import CompanyProfile  # noqa: E402
from fiscal_period_util import normalize_fiscal_period, prior_fiscal_period  # noqa: E402
from quarter_registry import ensure_registry  # noqa: E402
from transcript_providers import get_provider, sync_inbox_transcripts  # noqa: E402

sys.path.insert(0, str(REPO_ROOT))
from src.llm.anthropic_client import AnthropicClient, BatchRequestItem  # noqa: E402

STAGE_ORDER = ("dimensions", "delta", "surprise", "novelty")
COMBINED_STAGES = ("delta", "surprise", "novelty")


def _resolve_ticker_args(ticker: str, args: argparse.Namespace) -> argparse.Namespace:
    """Per-ticker override of --quarters/--extra-output-quarters.

    When --new-quarter is used, mirrors run_company_pipeline.py's
    resolve_new_quarter_args(): auto-insert the prior fiscal period as a
    prior-only backfill when it isn't in that ticker's registry yet, since
    each ticker's registry state differs (a steady-state ticker won't need
    the backfill; a ticker mid-historical-backfill might).
    """
    ns = argparse.Namespace(**vars(args))
    if args.new_quarter:
        fp = normalize_fiscal_period(args.new_quarter)
        reg = ensure_registry(ticker)
        quarters = [fp]
        prior = prior_fiscal_period(fp)
        if prior and prior not in reg.get("scored_quarters", {}):
            quarters.insert(0, prior)
            print(f"[{ticker}] prior quarter {prior} not in registry — will score it first for delta baseline.")
        ns.quarters = quarters
        ns.extra_output_quarters = [fp]
    return ns


def _run_dimensions_group(
    tickers: list[str],
    per_ticker_args: dict[str, argparse.Namespace],
    client: AnthropicClient,
    use_rescue: bool,
    provider,
    model: str,
    args: argparse.Namespace,
) -> dict[str, int]:
    print("\n=== Batch group 1: dimensions (all tickers) ===")
    scorer = dim_mod.DimensionScorer(client, use_rescue=use_rescue)

    per_ticker_scope: dict[str, dim_mod.DimensionScope] = {}
    per_ticker_prepared: dict[str, list[dict]] = {}
    per_ticker_by_fp: dict[str, dict[str, dict]] = {}
    per_ticker_failed_cov: dict[str, list[dict]] = {}
    all_items: list[BatchRequestItem] = []
    id_to_ticker_fp: dict[str, tuple[str, str]] = {}

    for ticker in tickers:
        try:
            scope = dim_mod.resolve_scope(ticker, per_ticker_args[ticker])
        except ValueError as exc:
            print(f"[{ticker}] {exc}", file=sys.stderr)
            continue
        if scope is None:
            continue
        prepared, failed_cov = dim_mod.prepare_items(scope, provider)
        per_ticker_scope[ticker] = scope
        per_ticker_prepared[ticker] = prepared
        per_ticker_by_fp[ticker] = {p["fp"]: p for p in prepared}
        per_ticker_failed_cov[ticker] = failed_cov
        for p in prepared:
            item = scorer.build_request(p["transcript"], scope.company.company_name)
            all_items.append(item)
            id_to_ticker_fp[item.custom_id] = (ticker, p["fp"])

    written: dict[str, int] = {}
    scored_by_ticker: dict[str, dict[str, object]] = {t: {} for t in per_ticker_prepared}

    # Even with zero batch-scoring items, a ticker's scope may still carry a
    # pure prior-only -> output-scope *promotion* (see resolve_scope()) that
    # needs finalize_and_write() to apply it — so don't bail out before that
    # loop below just because there's nothing to submit to the Batch API.
    if not all_items:
        print("No dimension-scoring work across any ticker (checking for prior-only promotions)…")
    else:
        outcomes = run_batch(
            client, all_items, scorer.RESPONSE_MODEL,
            poll_interval=args.batch_poll_interval, timeout=args.batch_timeout,
        )

        retry: list[tuple[str, str]] = []
        for item in all_items:
            ticker, fp = id_to_ticker_fp[item.custom_id]
            outcome = outcomes.get(item.custom_id)
            if outcome is None or not outcome.ok:
                print(f"  ! [{ticker} {fp}] batch item failed "
                      f"({outcome.error if outcome else 'missing'}) — will retry synchronously")
                retry.append((ticker, fp))
                continue
            transcript = per_ticker_by_fp[ticker][fp]["transcript"]
            scored_by_ticker[ticker][fp] = scorer.finalize(
                outcome.parsed, outcome.llm_result, item.custom_id, transcript.raw_text
            )

        for ticker, fp in retry:
            transcript = per_ticker_by_fp[ticker][fp]["transcript"]
            company_name = per_ticker_scope[ticker].company.company_name
            print(f"[{ticker} {fp}] scoring dimensions (sync retry)…")
            scored_by_ticker[ticker][fp] = scorer.score(transcript, company_name)

    for ticker, scope in per_ticker_scope.items():
        n = dim_mod.finalize_and_write(
            ticker, scope.company, scope, per_ticker_prepared[ticker],
            per_ticker_failed_cov[ticker], scored_by_ticker[ticker], model,
        )
        written[ticker] = n
    return written


def _delta_kwargs(scorer: "delta_mod.DeltaScorer", p: dict) -> dict:
    if scorer.context == delta_mod.CONTEXT_BOTH_TRANSCRIPTS:
        return {"prior_transcript": p["prior_transcript"]}
    return {"prior_summary_block": p["prior_block"]}


@dataclass
class _StageAdapter:
    resolve_scope: Callable
    prepare_items: Callable
    finalize_and_write: Callable
    response_model: type
    build_item: Callable[[object, CompanyProfile, dict], BatchRequestItem]
    sync_score: Callable[[object, CompanyProfile, dict], object]
    key_of: Callable[[dict], str]


_COMBINED_ADAPTERS: dict[str, _StageAdapter] = {
    "delta": _StageAdapter(
        resolve_scope=delta_mod.resolve_scope,
        prepare_items=delta_mod.prepare_items,
        finalize_and_write=delta_mod.finalize_and_write,
        response_model=delta_mod.DeltaScorer.RESPONSE_MODEL,
        build_item=lambda scorer, company, p: scorer.build_request(
            p["transcript"], p["prior_period"], company.company_name, **_delta_kwargs(scorer, p)
        ),
        sync_score=lambda scorer, company, p: scorer.score(
            p["transcript"], p["prior_period"], company.company_name, **_delta_kwargs(scorer, p)
        ),
        key_of=lambda p: p["current_period"],
    ),
    "surprise": _StageAdapter(
        resolve_scope=surprise_mod.resolve_scope,
        prepare_items=surprise_mod.prepare_items,
        finalize_and_write=surprise_mod.finalize_and_write,
        response_model=surprise_mod.SurpriseScorer.RESPONSE_MODEL,
        build_item=lambda scorer, company, p: scorer.build_request(
            p["transcript"], p["consensus_block"], company.company_name, p["level_block"]
        ),
        sync_score=lambda scorer, company, p: scorer.score(
            p["transcript"], p["consensus_block"], company.company_name, p["level_block"]
        ),
        key_of=lambda p: p["fp"],
    ),
    "novelty": _StageAdapter(
        resolve_scope=novelty_mod.resolve_scope,
        prepare_items=novelty_mod.prepare_items,
        finalize_and_write=novelty_mod.finalize_and_write,
        response_model=novelty_mod.NoveltyScorer.RESPONSE_MODEL,
        build_item=lambda scorer, company, p: scorer.build_request(
            p["transcript"], p["prior_block"], company.company_name
        ),
        sync_score=lambda scorer, company, p: scorer.score(
            p["transcript"], p["prior_block"], company.company_name
        ),
        key_of=lambda p: p["fp"],
    ),
}


def _make_combined_scorer(stage: str, client: AnthropicClient, use_rescue: bool, delta_context: str):
    if stage == "delta":
        return delta_mod.DeltaScorer(client, context=delta_context, use_rescue=use_rescue)
    if stage == "surprise":
        return surprise_mod.SurpriseScorer(client, use_rescue=use_rescue)
    if stage == "novelty":
        return novelty_mod.NoveltyScorer(client, use_rescue=use_rescue)
    raise ValueError(f"Unknown combined stage {stage!r}")


def _run_combined_group(
    stage_names: list[str],
    tickers: list[str],
    per_ticker_args: dict[str, argparse.Namespace],
    client: AnthropicClient,
    use_rescue: bool,
    delta_context: str,
    provider,
    model: str,
    args: argparse.Namespace,
) -> dict[str, dict[str, int]]:
    print(f"\n=== Batch group 2: {' + '.join(stage_names)} (all tickers, combined) ===")
    scorers = {s: _make_combined_scorer(s, client, use_rescue, delta_context) for s in stage_names}

    scopes: dict[tuple[str, str], object] = {}
    prepareds: dict[tuple[str, str], list[dict]] = {}
    all_items: list[BatchRequestItem] = []
    item_owner: dict[str, tuple[str, str, str]] = {}  # custom_id -> (stage, ticker, key)
    response_models: dict[str, type] = {}

    for stage in stage_names:
        adapter = _COMBINED_ADAPTERS[stage]
        for ticker in tickers:
            try:
                scope = adapter.resolve_scope(ticker, per_ticker_args[ticker])
            except (FileNotFoundError, ValueError) as exc:
                print(f"[{ticker}] {stage}: {exc}", file=sys.stderr)
                continue
            if scope is None:
                continue
            prepared = adapter.prepare_items(scope, provider)
            if not prepared:
                continue
            scopes[(stage, ticker)] = scope
            prepareds[(stage, ticker)] = prepared
            company = scope.company
            scorer = scorers[stage]
            for p in prepared:
                item = adapter.build_item(scorer, company, p)
                all_items.append(item)
                key = adapter.key_of(p)
                item_owner[item.custom_id] = (stage, ticker, key)
                response_models[item.custom_id] = adapter.response_model

    written: dict[str, dict[str, int]] = {t: {} for t in tickers}
    if not all_items:
        print(f"No {'/'.join(stage_names)} work across any ticker.")
        return written

    outcomes = run_batch(
        client, all_items, response_models,
        poll_interval=args.batch_poll_interval, timeout=args.batch_timeout,
    )

    scored: dict[tuple[str, str], dict[str, object]] = {}
    retry: list[tuple[str, str, str]] = []
    for item in all_items:
        stage, ticker, key = item_owner[item.custom_id]
        outcome = outcomes.get(item.custom_id)
        if outcome is None or not outcome.ok:
            print(f"  ! [{stage} {ticker} {key}] batch item failed "
                  f"({outcome.error if outcome else 'missing'}) — will retry synchronously")
            retry.append((stage, ticker, key))
            continue
        adapter = _COMBINED_ADAPTERS[stage]
        prepared = prepareds[(stage, ticker)]
        p = next(x for x in prepared if adapter.key_of(x) == key)
        scorer = scorers[stage]
        scored.setdefault((stage, ticker), {})[key] = scorer.finalize(
            outcome.parsed, outcome.llm_result, item.custom_id, p["transcript"].raw_text
        )

    for stage, ticker, key in retry:
        adapter = _COMBINED_ADAPTERS[stage]
        prepared = prepareds[(stage, ticker)]
        p = next(x for x in prepared if adapter.key_of(x) == key)
        company = scopes[(stage, ticker)].company
        scorer = scorers[stage]
        print(f"[{stage} {ticker} {key}] sync retry…")
        scored.setdefault((stage, ticker), {})[key] = adapter.sync_score(scorer, company, p)

    for (stage, ticker), scored_by_key in scored.items():
        adapter = _COMBINED_ADAPTERS[stage]
        scope = scopes[(stage, ticker)]
        prepared = prepareds[(stage, ticker)]
        n = adapter.finalize_and_write(ticker, scope.company, scope, prepared, scored_by_key, model)
        written[ticker][stage] = n

    return written


def _print_summary(written: dict[str, dict[str, int]]) -> None:
    print("\n=== Summary (rows written per ticker/stage) ===")
    for ticker, stage_counts in written.items():
        if not stage_counts:
            print(f"  {ticker}: nothing written")
            continue
        parts = ", ".join(f"{s}={n}" for s, n in stage_counts.items())
        print(f"  {ticker}: {parts}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Batch-score dimensions/delta/surprise/novelty across multiple tickers "
        "in the minimum number of Anthropic Message Batches (2, regardless of ticker count)."
    )
    ap.add_argument("--tickers", nargs="+", required=True, help="Ticker symbols to score together.")
    ap.add_argument(
        "--scope",
        choices=("five_year",),
        help="Quarter scope preset, applied to whichever ticker it's valid for (AMZN only).",
    )
    ap.add_argument(
        "--quarters",
        nargs="+",
        default=[],
        help="Re-score only these fiscal periods (applied to every ticker in --tickers).",
    )
    ap.add_argument(
        "--extra-output-quarters",
        nargs="+",
        default=[],
        help="Treat these fiscal periods as output scope even if not in company_config "
        "(applied to every ticker in --tickers).",
    )
    ap.add_argument(
        "--new-quarter",
        metavar="FYyyyy-Qn",
        help="Score one new output quarter incrementally for every ticker in --tickers "
        "(auto-backfills each ticker's prior quarter if missing from its registry).",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Re-score even when the registry marks a quarter/stage complete.",
    )
    ap.add_argument(
        "--stages",
        nargs="+",
        default=list(STAGE_ORDER),
        choices=STAGE_ORDER,
        help="Which stages to run (default: all four, in dependency order).",
    )
    ap.add_argument("--batch-poll-interval", type=float, default=30.0, help="Seconds between batch status polls.")
    ap.add_argument(
        "--batch-timeout",
        type=float,
        default=None,
        help="Max seconds to wait per batch (default: no timeout, up to Anthropic's 24h SLA).",
    )
    args = ap.parse_args()

    tickers = [t.strip().upper() for t in args.tickers]
    # Preserve canonical dependency order regardless of how --stages was typed.
    stages = [s for s in STAGE_ORDER if s in args.stages]

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY not set (checked Structured Narrative/.env "
              "and repo-root .env).", file=sys.stderr)
        return 1
    model = os.getenv("DIMENSION_MODEL", dim_mod.DEFAULT_MODEL)
    use_rescue = os.getenv("DIMENSION_RESCUE", "1").strip().lower() not in ("0", "false", "no", "off")
    delta_context = delta_mod.parse_delta_context()

    try:
        provider = get_provider()
    except Exception as exc:
        print(f"Error initializing transcript provider: {exc}", file=sys.stderr)
        return 1

    for ticker in tickers:
        sync_inbox_transcripts(ticker, verbose=True)

    per_ticker_args = {t: _resolve_ticker_args(t, args) for t in tickers}

    # One shared client for the whole run so usage_summary() reports
    # consolidated cost/token totals across both batch groups.
    client = AnthropicClient(api_key=api_key, model=model, max_retries=1)

    written: dict[str, dict[str, int]] = {t: {} for t in tickers}

    if "dimensions" in stages:
        dims_written = _run_dimensions_group(tickers, per_ticker_args, client, use_rescue, provider, model, args)
        for t, n in dims_written.items():
            written[t]["dimensions"] = n

    remaining = [s for s in COMBINED_STAGES if s in stages]
    if remaining:
        combined_written = _run_combined_group(
            remaining, tickers, per_ticker_args, client, use_rescue, delta_context, provider, model, args
        )
        for t, stage_counts in combined_written.items():
            written[t].update(stage_counts)

    _print_summary(written)
    print(client.usage_summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
