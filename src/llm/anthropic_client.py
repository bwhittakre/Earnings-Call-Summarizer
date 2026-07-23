from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from src.paths import ERRORS_DIR
from src.schemas.models import LLMResult, TokenUsage

T = TypeVar("T", bound=BaseModel)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


def load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _loads_json(raw: str) -> dict:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        import json_repair

        return json_repair.loads(raw)


def extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return _loads_json(text)
    except json.JSONDecodeError:
        pass

    fence_match = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence_match:
        return _loads_json(fence_match.group(1))

    brace_match = re.search(r"\{.*\}", text, re.DOTALL)
    if brace_match:
        return _loads_json(brace_match.group(0))

    raise ValueError("No valid JSON object found in model response")


def save_error_artifact(label: str, raw_response: str, error: Exception) -> Path:
    ERRORS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = re.sub(r"[^\w\-]+", "_", label)
    path = ERRORS_DIR / f"{safe_label}_{timestamp}.txt"
    path.write_text(
        f"Error: {error}\n\n--- Raw Response ---\n{raw_response}",
        encoding="utf-8",
    )
    return path


def _system_blocks(system_prompt: str) -> list[dict]:
    """Wrap a system prompt as a single cacheable content block.

    Every scorer (dimension/delta/surprise/novelty/rescue) loads its system
    prompt once from a prompt file and reuses the identical string across
    every call for that stage. Marking it with an ephemeral cache breakpoint
    means the 2nd+ call within the cache TTL reads it at the discounted
    cache-read rate instead of paying full input price again. Used by both
    the synchronous (`complete_json`) and batch (`submit_batch`) request
    paths so caching benefits apply everywhere uniformly.
    """
    return [
        {
            "type": "text",
            "text": system_prompt,
            "cache_control": {"type": "ephemeral"},
        }
    ]


@dataclass
class BatchRequestItem:
    """One request to include in an Anthropic Message Batch.

    Mirrors the (system_prompt, user_content) pair `complete_json` takes, so
    the same call site can be reused for either the sync or batch path.
    """

    custom_id: str
    system_prompt: str
    user_content: str
    max_tokens: int = 16384


@dataclass
class BatchItemResult:
    """One normalized result from a completed Message Batch.

    `error` is set (and `raw_text`/`usage` are None) when the item did not
    succeed — a non-"succeeded" batch result, or a request-level failure.
    Callers typically fall back to a synchronous retry for these.
    """

    custom_id: str
    raw_text: str | None
    usage: TokenUsage | None
    error: str | None


class AnthropicClient:
    def __init__(self, api_key: str, model: str, max_retries: int = 1):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_retries = max_retries
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cache_creation_tokens = 0
        self.total_cache_read_tokens = 0

    def _usage_from_response(self, response_usage: Any) -> TokenUsage:
        return TokenUsage(
            input_tokens=response_usage.input_tokens,
            output_tokens=response_usage.output_tokens,
            cache_creation_input_tokens=(
                getattr(response_usage, "cache_creation_input_tokens", 0) or 0
            ),
            cache_read_input_tokens=(
                getattr(response_usage, "cache_read_input_tokens", 0) or 0
            ),
        )

    def _accumulate_usage(self, usage: TokenUsage) -> None:
        self.total_input_tokens += usage.input_tokens
        self.total_output_tokens += usage.output_tokens
        self.total_cache_creation_tokens += usage.cache_creation_input_tokens
        self.total_cache_read_tokens += usage.cache_read_input_tokens

    def _parse_response(self, raw: str, response_model: type[T]) -> T:
        payload = extract_json(raw)
        return response_model.model_validate(payload)

    def complete_json(
        self,
        system_prompt: str,
        user_content: str,
        response_model: type[T],
        label: str,
    ) -> tuple[T, LLMResult]:
        last_error: Exception | None = None
        last_raw = ""

        for attempt in range(self.max_retries + 1):
            response = self.client.messages.create(
                model=self.model,
                max_tokens=16384,
                system=_system_blocks(system_prompt),
                messages=[{"role": "user", "content": user_content}],
            )

            raw = "".join(
                block.text for block in response.content if block.type == "text"
            )
            last_raw = raw

            usage = self._usage_from_response(response.usage)
            self._accumulate_usage(usage)

            try:
                parsed = self._parse_response(raw, response_model)
                return parsed, LLMResult(usage=usage, raw_response=raw)
            except (ValueError, ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    continue
                save_error_artifact(label, raw, exc)
                raise ValueError(
                    f"Failed to parse LLM response for '{label}' after "
                    f"{self.max_retries + 1} attempt(s). "
                    f"Raw response saved to output_confidence/errors/."
                ) from exc

        raise ValueError(f"Unexpected LLM failure for '{label}'") from last_error

    # ------------------------------------------------------------------
    # Message Batches API — async, ~50% off input+output tokens vs. the
    # synchronous path above. Submit a whole stage's worth of requests as
    # one batch, poll until it finishes, then parse results one at a time.
    # ------------------------------------------------------------------

    def submit_batch(self, items: list[BatchRequestItem]) -> str:
        """Submit `items` as one Anthropic Message Batch. Returns the batch id."""
        requests = [
            {
                "custom_id": item.custom_id,
                "params": {
                    "model": self.model,
                    "max_tokens": item.max_tokens,
                    "system": _system_blocks(item.system_prompt),
                    "messages": [{"role": "user", "content": item.user_content}],
                },
            }
            for item in items
        ]
        batch = self.client.messages.batches.create(requests=requests)
        return batch.id

    def get_batch(self, batch_id: str) -> Any:
        """Return the current MessageBatch (has `.processing_status`, `.request_counts`)."""
        return self.client.messages.batches.retrieve(batch_id)

    def retrieve_batch_results(self, batch_id: str) -> list[BatchItemResult]:
        """Fetch and normalize every item's result from a finished batch.

        Only call this once `get_batch(batch_id).processing_status == "ended"`.
        Also rolls each succeeded item's usage into the running totals, same
        as `complete_json` does for the sync path.
        """
        results: list[BatchItemResult] = []
        for entry in self.client.messages.batches.results(batch_id):
            result = entry.result
            if result.type == "succeeded":
                message = result.message
                raw = "".join(
                    block.text for block in message.content if block.type == "text"
                )
                usage = self._usage_from_response(message.usage)
                self._accumulate_usage(usage)
                results.append(
                    BatchItemResult(
                        custom_id=entry.custom_id,
                        raw_text=raw,
                        usage=usage,
                        error=None,
                    )
                )
            else:
                error_detail = getattr(result, "error", None)
                results.append(
                    BatchItemResult(
                        custom_id=entry.custom_id,
                        raw_text=None,
                        usage=None,
                        error=f"{result.type}: {error_detail}" if error_detail else result.type,
                    )
                )
        return results

    def parse_batch_result(self, result: BatchItemResult, response_model: type[T]) -> T:
        """Parse+validate one succeeded BatchItemResult (single attempt, no retry).

        Batch items don't get the synchronous path's automatic retry loop —
        raises on failure so the caller can decide to retry that item via
        `complete_json` instead.
        """
        if result.error:
            raise ValueError(f"Batch item '{result.custom_id}' did not succeed: {result.error}")
        raw = result.raw_text or ""
        try:
            return self._parse_response(raw, response_model)
        except (ValueError, ValidationError, json.JSONDecodeError) as exc:
            save_error_artifact(result.custom_id, raw, exc)
            raise ValueError(
                f"Failed to parse batch LLM response for '{result.custom_id}'. "
                f"Raw response saved to output_confidence/errors/."
            ) from exc

    def usage_summary(self) -> str:
        return (
            f"Total tokens — input: {self.total_input_tokens:,}, "
            f"output: {self.total_output_tokens:,}, "
            f"total: {self.total_input_tokens + self.total_output_tokens:,} | "
            f"cache — write: {self.total_cache_creation_tokens:,}, "
            f"read: {self.total_cache_read_tokens:,}"
        )
