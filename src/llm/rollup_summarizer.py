from __future__ import annotations

import json

from src.llm.anthropic_client import AnthropicClient, load_prompt
from src.schemas.models import LLMResult, QuarterSummary, RollupSummary


class RollupSummarizer:
    def __init__(self, client: AnthropicClient):
        self.client = client
        self.system_prompt = load_prompt("rollup.txt")

    def summarize(
        self,
        company_name: str,
        quarter_summaries: list[QuarterSummary],
    ) -> tuple[RollupSummary, LLMResult]:
        payload = [
            summary.model_dump(exclude={"summary_type"}) for summary in quarter_summaries
        ]
        user_content = (
            f"Company: {company_name}\n\n"
            f"Quarter summaries (JSON):\n{json.dumps(payload, indent=2)}"
        )
        summary, result = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=RollupSummary,
            label=f"{company_name}_rollup",
        )
        summary.company_name = company_name
        summary.quarter = "All (8Q rollup)"
        summary.summary_type = "rollup"
        return summary, result
