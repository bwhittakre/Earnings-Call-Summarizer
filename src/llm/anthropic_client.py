from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

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


class AnthropicClient:
    def __init__(self, api_key: str, model: str, max_retries: int = 1):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_retries = max_retries
        self.total_input_tokens = 0
        self.total_output_tokens = 0

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
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )

            raw = "".join(
                block.text for block in response.content if block.type == "text"
            )
            last_raw = raw

            usage = TokenUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            )
            self.total_input_tokens += usage.input_tokens
            self.total_output_tokens += usage.output_tokens

            try:
                payload = extract_json(raw)
                parsed = response_model.model_validate(payload)
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

    def usage_summary(self) -> str:
        return (
            f"Total tokens — input: {self.total_input_tokens:,}, "
            f"output: {self.total_output_tokens:,}, "
            f"total: {self.total_input_tokens + self.total_output_tokens:,}"
        )
