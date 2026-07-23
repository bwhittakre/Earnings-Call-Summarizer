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
        batch = client.get_batch(batch_id)
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
