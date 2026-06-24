from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ConfidenceLevel = Literal["High", "Medium", "Low"]
SummaryType = Literal["quarter", "rollup"]


class QuarterSummary(BaseModel):
    company_name: str
    quarter: str
    what_happened: list[str] = Field(min_length=1)
    positives: list[str]
    negatives: list[str]
    confidence: ConfidenceLevel
    summary_type: SummaryType = "quarter"


class RollupSummary(BaseModel):
    company_name: str
    quarter: str = "All (8Q rollup)"
    what_happened: list[str] = Field(min_length=1)
    positives: list[str]
    negatives: list[str]
    confidence: ConfidenceLevel
    summary_type: SummaryType = "rollup"


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int


class LLMResult(BaseModel):
    usage: TokenUsage
    raw_response: str
