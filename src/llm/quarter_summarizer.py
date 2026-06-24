from __future__ import annotations

from src.llm.anthropic_client import AnthropicClient, load_prompt
from src.schemas.models import LLMResult, QuarterSummary


class QuarterSummarizer:
    def __init__(self, client: AnthropicClient):
        self.client = client
        self.system_prompt = load_prompt("quarter.txt")

    def summarize(
        self,
        company_name: str,
        quarter: str,
        transcript_text: str,
    ) -> tuple[QuarterSummary, LLMResult]:
        user_content = (
            f"Company: {company_name}\n"
            f"Quarter: {quarter}\n\n"
            f"--- TRANSCRIPT ---\n{transcript_text}"
        )
        summary, result = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=QuarterSummary,
            label=f"{company_name}_{quarter}_quarter",
        )
        summary.company_name = company_name
        summary.quarter = quarter
        summary.summary_type = "quarter"
        return summary, result
