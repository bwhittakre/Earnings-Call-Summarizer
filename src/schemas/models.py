from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

ConfidenceLevel = Literal["High", "Medium", "Low"]
SummaryType = Literal["quarter", "rollup"]
RescueVerdict = Literal["rescued", "drop"]


class EvidenceClaim(BaseModel):
    claim: str = Field(min_length=1)
    excerpt: str = Field(min_length=1)


class ConfidenceEvidence(BaseModel):
    level: ConfidenceLevel
    excerpt: str = Field(min_length=1)


class EvidenceBackedQuarterSummary(BaseModel):
    company_name: str
    quarter: str
    call_date: str | None = None
    what_happened: list[EvidenceClaim] = Field(min_length=1)
    positives: list[EvidenceClaim]
    negatives: list[EvidenceClaim]
    confidence_score: int = Field(ge=-100, le=100)
    analysis: list[EvidenceClaim] = Field(min_length=1)


class AnalysisRepairResponse(BaseModel):
    analysis: list[EvidenceClaim] = Field(min_length=1)


class EvidenceBackedRollupSummary(BaseModel):
    company_name: str
    quarter: str = "All (8Q rollup)"
    what_happened: list[EvidenceClaim] = Field(min_length=1)
    positives: list[EvidenceClaim]
    negatives: list[EvidenceClaim]
    confidence: ConfidenceEvidence


class QuarterSummary(BaseModel):
    company_name: str
    quarter: str
    call_date: str | None = None
    what_happened: list[str] = Field(min_length=1)
    positives: list[str]
    negatives: list[str]
    transcript_only_confidence_score: int = Field(ge=-100, le=100)
    confidence_score: int = Field(ge=-100, le=100)
    analysis: list[EvidenceClaim] = Field(min_length=1)
    summary_type: SummaryType = "quarter"


class RollupSummary(BaseModel):
    company_name: str
    quarter: str = "All (8Q rollup)"
    what_happened: list[str] = Field(min_length=1)
    positives: list[str]
    negatives: list[str]
    confidence: ConfidenceLevel
    summary_type: SummaryType = "rollup"


class RescueReview(BaseModel):
    field: str
    index: int | None = None
    verdict: RescueVerdict
    reason: str
    canonical_excerpt: str | None = None

    @model_validator(mode="after")
    def require_canonical_for_rescue(self) -> RescueReview:
        if self.verdict == "rescued" and not self.canonical_excerpt:
            raise ValueError("canonical_excerpt is required when verdict is rescued")
        return self


class RescueJudgeResult(BaseModel):
    reviews: list[RescueReview]


class TokenUsage(BaseModel):
    input_tokens: int
    output_tokens: int


class LLMResult(BaseModel):
    usage: TokenUsage
    raw_response: str


def quarter_summary_from_evidence(
    evidence: EvidenceBackedQuarterSummary,
) -> QuarterSummary:
    from src.scoring.analysis_score import (
        apply_confidence_score_from_analysis,
        compute_transcript_only_confidence_score,
    )

    evidence = apply_confidence_score_from_analysis(evidence)
    return QuarterSummary(
        company_name=evidence.company_name,
        quarter=evidence.quarter,
        call_date=evidence.call_date,
        what_happened=[item.claim for item in evidence.what_happened],
        positives=[item.claim for item in evidence.positives],
        negatives=[item.claim for item in evidence.negatives],
        confidence_score=evidence.confidence_score,
        transcript_only_confidence_score=compute_transcript_only_confidence_score(
            evidence.analysis
        ),
        analysis=evidence.analysis,
        summary_type="quarter",
    )


def rollup_summary_from_evidence(
    evidence: EvidenceBackedRollupSummary,
) -> RollupSummary:
    return RollupSummary(
        company_name=evidence.company_name,
        quarter=evidence.quarter,
        what_happened=[item.claim for item in evidence.what_happened],
        positives=[item.claim for item in evidence.positives],
        negatives=[item.claim for item in evidence.negatives],
        confidence=evidence.confidence.level,
        summary_type="rollup",
    )
