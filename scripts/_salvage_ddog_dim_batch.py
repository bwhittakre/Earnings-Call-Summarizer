"""Write succeeded DDOG dimension results from a canceled Anthropic batch."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
load_dotenv(SN / ".env")
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(SN))
sys.path.insert(0, str(ROOT))

import run_dimension_scoring as dim_mod  # noqa: E402
from src.llm.anthropic_client import AnthropicClient, BatchItemResult  # noqa: E402
from src.schemas.models import LLMResult  # noqa: E402
from transcript_providers import get_provider  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch-id", required=True)
    args = ap.parse_args()

    api_key = os.environ["ANTHROPIC_API_KEY"]
    model = os.getenv("DIMENSION_MODEL", dim_mod.DEFAULT_MODEL)
    client = AnthropicClient(api_key=api_key, model=model)
    batch = client.get_batch(args.batch_id)
    print(f"status={batch.processing_status} counts={getattr(batch, 'request_counts', None)}")
    if batch.processing_status != "ended":
        print("batch has not ended; nothing to salvage")
        return 1

    succeeded: dict[str, object] = {}
    canceled: list[str] = []
    other: list[tuple[str, str]] = []
    for entry in client.client.messages.batches.results(args.batch_id):
        cid = entry.custom_id
        result = entry.result
        if result.type == "succeeded":
            succeeded[cid] = result
        elif result.type == "canceled":
            canceled.append(cid)
        else:
            other.append((cid, result.type))

    print(f"succeeded={len(succeeded)} canceled={len(canceled)} other={len(other)}")
    for cid in sorted(canceled):
        print(f"  canceled {cid}")
    for cid, kind in other:
        print(f"  {kind} {cid}")

    fps = []
    for cid in succeeded:
        # DDOG_FY2020-Q1_dimensions
        fps.append(cid.split("_")[1])
    fps = sorted(set(fps))
    print(f"writing dimensions for: {', '.join(fps)}")

    ns = argparse.Namespace(
        ticker="DDOG",
        quarters=fps,
        extra_output_quarters=[],
        force=False,
        scope=None,
        execution_mode="sync",
        confirm_expensive_sync=True,
        batch=False,
        batch_poll_interval=30.0,
        batch_timeout=None,
    )
    scope = dim_mod.resolve_scope("DDOG", ns)
    if scope is None:
        print("resolve_scope returned None — already written?")
        return 0
    provider = get_provider()
    prepared, failed = dim_mod.prepare_items(scope, provider)
    scorer = dim_mod.DimensionScorer(client, use_rescue=True)
    scored = {}
    for p in prepared:
        cid = f"DDOG_{p['fp']}_dimensions"
        result = succeeded.get(cid)
        if result is None:
            print(f"  ! no succeeded result for {cid}")
            continue
        message = result.message
        raw = "".join(block.text for block in message.content if block.type == "text")
        usage = client._usage_from_response(message.usage)
        item = BatchItemResult(custom_id=cid, raw_text=raw, usage=usage, error=None)
        parsed = client.parse_batch_result(item, scorer.RESPONSE_MODEL)
        llm_result = LLMResult(usage=usage, raw_response=raw)
        scored[p["fp"]] = scorer.finalize(parsed, llm_result, cid, p["transcript"].raw_text)
        print(f"  parsed {p['fp']}")

    prepared = [p for p in prepared if p["fp"] in scored]
    n = dim_mod.finalize_and_write("DDOG", scope.company, scope, prepared, failed, scored, model)
    print(f"wrote {n} dimension view quarter(s)")
    return 0 if n else 1


if __name__ == "__main__":
    raise SystemExit(main())
