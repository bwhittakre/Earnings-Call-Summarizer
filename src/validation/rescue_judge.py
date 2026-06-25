from __future__ import annotations

import json

from src.llm.anthropic_client import AnthropicClient, load_prompt
from src.schemas.models import LLMResult, RescueJudgeResult
from src.validation.evidence_processor import failures_to_review_payload
from src.validation.evidence_validator import ValidationFailure, ValidationResult

CANONICAL_RETRY_FEEDBACK = (
    "Your canonical_excerpt was not found verbatim in the source. "
    "Return rescued with a shorter contiguous quote copied exactly from SOURCE TEXT. "
    "Do not paraphrase the quote."
)


class RescueJudge:
    def __init__(self, client: AnthropicClient):
        self.client = client
        self.system_prompt = load_prompt("rescue_judge.txt")

    def review_failures(
        self,
        failures: list[ValidationFailure],
        source_text: str,
        label: str,
        feedback: str | None = None,
    ) -> tuple[RescueJudgeResult, LLMResult]:
        payload = failures_to_review_payload(failures)
        user_content = f"Label: {label}\n\n--- SOURCE TEXT ---\n{source_text}\n\n"
        if feedback:
            user_content += f"Feedback:\n{feedback}\n\n"
        user_content += f"Bullets to review (JSON):\n{json.dumps(payload, indent=2)}"
        return self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=RescueJudgeResult,
            label=f"{label}_rescue",
        )

    def review_single_failure(
        self,
        failure: ValidationFailure,
        source_text: str,
        label: str,
        feedback: str | None = None,
    ) -> tuple[RescueJudgeResult, LLMResult]:
        return self.review_failures([failure], source_text, label, feedback=feedback)

    def review_validation_result(
        self,
        validation: ValidationResult,
        source_text: str,
        label: str,
    ) -> tuple[RescueJudgeResult, LLMResult]:
        return self.review_failures(validation.failures, source_text, label)
