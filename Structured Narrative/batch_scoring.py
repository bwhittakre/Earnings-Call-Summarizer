#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Shared Anthropic Message Batch orchestration for the 4 scoring stages.
========================================================================

Each `run_*_scoring.py` script builds one `BatchRequestItem` per quarter (via
its scorer's `build_request()`), then calls `run_batch()` here to submit them
as a single Anthropic Message Batch, poll to completion, and get back parsed
results keyed by `custom_id`. The caller is responsible for mapping
`custom_id` back to the fiscal period/transcript it built the request for
(the scorers always use `custom_id` as their audit label, e.g.
`"{ticker}_{fiscal_period}_dimensions"`), and for calling the scorer's
`finalize()` on each successful result.

Any item that errors (a non-"succeeded" batch result, or a parse failure) is
reported back with its error message rather than raised — callers fall back
to a synchronous `scorer.score(...)` retry for those, since Batch API items
don't get the synchronous path's automatic retry loop.
"""
from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.llm.anthropic_client import AnthropicClient, BatchRequestItem  # noqa: E402
from src.schemas.models import LLMResult  # noqa: E402

T = TypeVar("T", bound=BaseModel)

# Anthropic's Batch API SLA is "processed within 24h"; small batches (the
# usual case here) often finish much faster in practice, but there is no
# guaranteed fast tier, so the default poll loop has no timeout.
DEFAULT_POLL_INTERVAL_SECONDS = 30.0
EXECUTION_MODES = ("auto", "sync", "batch")
# Anthropic Claude API global list prices, USD per million tokens. Cache
# creation assumes the default 5-minute TTL. Batch mode receives the published
# 50% discount across token categories.
MODEL_PRICING_USD_PER_MTOK = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_write": 3.75,
        "cache_read": 0.30,
    },
}


@dataclass(frozen=True)
class ExecutionModeResolution:
    """Resolved transport and the requested job cardinality that selected it."""

    requested_mode: str
    resolved_mode: str
    ticker_count: int
    quarter_count: int

    @property
    def item_count(self) -> int:
        return self.ticker_count * self.quarter_count

    def summary(self) -> str:
        return (
            f"Execution mode — requested: {self.requested_mode}, resolved: "
            f"{self.resolved_mode} | requested job: {self.ticker_count} ticker(s) "
            f"x {self.quarter_count} quarter(s) = {self.item_count} ticker-quarter(s)"
        )


def add_execution_mode_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the shared mode interface while retaining ``--batch`` as an alias."""
    parser.add_argument(
        "--execution-mode",
        choices=EXECUTION_MODES,
        default=None,
        help="Scoring transport (default: auto; one ticker/quarter uses sync, larger jobs batch).",
    )
    parser.add_argument(
        "--confirm-expensive-sync",
        action="store_true",
        help="Confirm full-price synchronous execution for jobs larger than one ticker-quarter.",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Deprecated alias for --execution-mode batch.",
    )


def resolve_execution_mode(
    requested_mode: str | None,
    *,
    ticker_count: int,
    quarter_count: int,
    batch_alias: bool = False,
    confirm_expensive_sync: bool = False,
) -> ExecutionModeResolution:
    """Resolve routing from requested cardinality, before registry skips.

    This intentionally does not inspect prepared/scorable items: a historical
    request with only one remaining registry gap must still use Batch pricing.
    """
    if ticker_count < 1 or quarter_count < 1:
        raise ValueError("Execution-mode routing requires at least one ticker and one quarter.")
    if batch_alias and requested_mode not in (None, "batch"):
        raise ValueError(
            "--batch conflicts with --execution-mode "
            f"{requested_mode}; remove --batch or select --execution-mode batch."
        )
    requested = "batch" if batch_alias else (requested_mode or "auto")
    resolved = (
        "sync"
        if requested == "auto" and ticker_count == 1 and quarter_count == 1
        else "batch" if requested == "auto" else requested
    )
    if resolved == "sync" and ticker_count * quarter_count > 1 and not confirm_expensive_sync:
        raise ValueError(
            "Synchronous scoring for more than one ticker-quarter is full-price. "
            "Use --confirm-expensive-sync to proceed, or select --execution-mode batch."
        )
    return ExecutionModeResolution(requested, resolved, ticker_count, quarter_count)


def requested_quarter_count(args: argparse.Namespace) -> int:
    """Return CLI-requested quarter cardinality, conservatively batch by default."""
    quarters = getattr(args, "quarters", None) or []
    if quarters:
        return len(set(quarters))
    if getattr(args, "new_quarter", None) or getattr(args, "baseline_quarter", None):
        return 1
    # Scope presets and unqualified company runs are historical/multi-quarter.
    return 2


def print_usage_report(client: AnthropicClient, mode: str, elapsed_seconds: float) -> None:
    """Print usage, timing, and a list-price estimate when the model is known."""
    print(client.usage_summary())
    print(f"Elapsed: {elapsed_seconds:.2f}s")
    discount = "Batch API discount applies" if mode == "batch" else "synchronous standard pricing"
    prices = MODEL_PRICING_USD_PER_MTOK.get(client.model)
    if prices is None:
        print(
            f"Estimated API cost: unavailable (no authoritative pricing map for {client.model}); "
            f"{discount}."
        )
        return

    multiplier = 0.5 if mode == "batch" else 1.0
    estimated_cost = multiplier * (
        client.total_input_tokens * prices["input"]
        + client.total_output_tokens * prices["output"]
        + client.total_cache_creation_tokens * prices["cache_write"]
        + client.total_cache_read_tokens * prices["cache_read"]
    ) / 1_000_000
    print(
        f"Estimated API cost: ${estimated_cost:.4f} USD "
        f"(global list price; 5-minute cache writes; {discount})."
    )


@dataclass
class BatchOutcome(Generic[T]):
    """One item's outcome from a completed batch: exactly one of
    (parsed, llm_result) or `error` is set."""

    custom_id: str
    parsed: T | None
    llm_result: LLMResult | None
    error: str | None

    @property
    def ok(self) -> bool:
        return self.error is None


def run_batch(
    client: AnthropicClient,
    items: list[BatchRequestItem],
    response_model: type[T] | dict[str, type[BaseModel]],
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float | None = None,
    sleep_fn=time.sleep,
) -> dict[str, BatchOutcome[T]]:
    """Submit `items` as one Message Batch, poll to completion, and return
    {custom_id: BatchOutcome} for every item. Empty input returns {}.

    `response_model` is either a single Pydantic model applied to every item
    (the common single-stage case), or a `{custom_id: model}` dict for mixed
    batches that combine items from different scoring stages (each stage has
    its own response schema) — see `run_universe_batch.py`.
    """
    if not items:
        return {}

    print(f"  Submitting batch of {len(items)} request(s)…")
    batch_id = client.submit_batch(items)
    print(f"  batch_id={batch_id} — polling (this can take minutes to ~24h)…")

    start = time.monotonic()
    while True:
        batch = None
        last_err = None
        for attempt in range(1, 7):
            try:
                batch = client.get_batch(batch_id)
                last_err = None
                break
            except Exception as exc:
                last_err = exc
                print(
                    f"    get_batch retry {attempt}/6 after {type(exc).__name__}",
                    flush=True,
                )
                sleep_fn(5 * attempt)
        if batch is None:
            raise last_err
        status = batch.processing_status
        counts = getattr(batch, "request_counts", None)
        elapsed = time.monotonic() - start
        print(f"    [{elapsed:.0f}s] status={status}" + (f" counts={counts}" if counts else ""))
        if status == "ended":
            break
        if timeout is not None and elapsed > timeout:
            raise TimeoutError(
                f"Batch {batch_id} did not finish within {timeout}s (status={status})"
            )
        sleep_fn(poll_interval)

    outcomes: dict[str, BatchOutcome[T]] = {}
    for item_result in client.retrieve_batch_results(batch_id):
        if item_result.error or item_result.usage is None:
            error = item_result.error or "succeeded result missing usage data"
            outcomes[item_result.custom_id] = BatchOutcome(
                custom_id=item_result.custom_id, parsed=None, llm_result=None, error=error
            )
            continue
        model = (
            response_model
            if isinstance(response_model, type)
            else response_model[item_result.custom_id]
        )
        try:
            parsed = client.parse_batch_result(item_result, model)
        except ValueError as exc:
            outcomes[item_result.custom_id] = BatchOutcome(
                custom_id=item_result.custom_id, parsed=None, llm_result=None, error=str(exc)
            )
            continue
        llm_result = LLMResult(usage=item_result.usage, raw_response=item_result.raw_text or "")
        outcomes[item_result.custom_id] = BatchOutcome(
            custom_id=item_result.custom_id, parsed=parsed, llm_result=llm_result, error=None
        )
    return outcomes
