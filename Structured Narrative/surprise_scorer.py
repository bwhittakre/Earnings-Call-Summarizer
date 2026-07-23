#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Focus 3: narrative SURPRISE (consensus vs management) scorer.
=============================================================

Compares management's earnings-call narrative to pre-call consensus context
(built from the quant spine) and optional Focus 1 level scores. Outputs per
dimension:

  * surprise_direction   more_bullish_than_expected | in_line | more_bearish_than_expected
  * surprise_magnitude   continuous -2.0..+2.0 (sign = direction vs expectations)
  * rationale + evidence from the current transcript (verified via verify_excerpts)

Deterministic quant anchors (dim z, agrees_with_quant, narrative_quant_gap) are
attached by run_surprise_scoring.py.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.llm.anthropic_client import AnthropicClient, BatchRequestItem  # noqa: E402
from src.schemas.models import EvidenceClaim, LLMResult  # noqa: E402
from src.validation.rescue_judge import RescueJudge  # noqa: E402

from dimension_scorer import (  # noqa: E402
    QUANT_COMPARABLE_DIMENSIONS,
    ScoredExcerpt,
    verify_excerpts,
)
from transcript_providers import Transcript  # noqa: E402

SURPRISE_PROMPT_PATH = HERE / "prompts" / "dimension_surprise_quant.txt"

VALID_DIRECTIONS = (
    "more_bullish_than_expected",
    "in_line",
    "more_bearish_than_expected",
)


class DimensionSurprise(BaseModel):
    dimension: str
    surprise_direction: str = "in_line"
    surprise_magnitude: float = Field(0.0, ge=-2, le=2)
    evidence: list[EvidenceClaim] = Field(default_factory=list)
    rationale: str = ""

    @field_validator("surprise_direction", mode="before")
    @classmethod
    def _normalize_direction(cls, v: object) -> str:
        s = str(v or "").strip().lower().replace(" ", "_")
        if s in VALID_DIRECTIONS:
            return s
        if "bullish" in s or "better" in s or "above" in s or "positive" in s:
            return "more_bullish_than_expected"
        if "bearish" in s or "worse" in s or "below" in s or "negative" in s:
            return "more_bearish_than_expected"
        return "in_line"


class TranscriptSurpriseSummary(BaseModel):
    company_name: str
    ticker: str
    fiscal_period: str
    as_of_date: str | None = None
    surprises: list[DimensionSurprise] = Field(min_length=1)


@dataclass
class ScoredSurprise:
    dimension: str
    surprise_direction: str
    surprise_magnitude: float
    rationale: str
    is_quant_comparable: bool
    evidence: list[ScoredExcerpt]

    @property
    def n_evidence(self) -> int:
        return len(self.evidence)

    @property
    def n_evidence_verified(self) -> int:
        return sum(1 for e in self.evidence if e.verified)

    @property
    def evidence_verified(self) -> bool:
        return all(e.verified for e in self.evidence) if self.evidence else True

    @property
    def excerpts(self) -> list[str]:
        return [e.excerpt for e in self.evidence]


@dataclass
class ScoredSurpriseTranscript:
    summary: TranscriptSurpriseSummary
    surprises: list[ScoredSurprise]
    llm_result: LLMResult

    @property
    def n_excerpts(self) -> int:
        return sum(s.n_evidence for s in self.surprises)

    @property
    def n_excerpts_verified(self) -> int:
        return sum(s.n_evidence_verified for s in self.surprises)


def _build_user_content(
    transcript: Transcript,
    consensus_block: str,
    company_name: str,
    level_block: str = "",
) -> str:
    parts = [
        f"Company: {company_name}",
        f"Ticker: {transcript.ticker}",
        f"Fiscal period: {transcript.fiscal_period}",
    ]
    if transcript.call_date:
        parts.append(f"Call date (as-of): {transcript.call_date}")
    parts.append(
        "Use only the consensus context, optional narrative levels, and transcript below. "
        "No post-call or outside knowledge."
    )
    parts.append("")
    parts.append("--- CONSENSUS CONTEXT (pre-call / reported surprise, point-in-time) ---")
    parts.append(consensus_block)
    if level_block.strip():
        parts.append("")
        parts.append("--- LLM NARRATIVE LEVELS (how management sounded this quarter) ---")
        parts.append(level_block)
    parts.append("")
    parts.append("--- EARNINGS CALL TRANSCRIPT ---")
    parts.append(transcript.raw_text)
    return "\n".join(parts)


class SurpriseScorer:
    RESPONSE_MODEL = TranscriptSurpriseSummary

    def __init__(
        self,
        client: AnthropicClient,
        prompt_path: Path = SURPRISE_PROMPT_PATH,
        use_rescue: bool = True,
    ):
        self.client = client
        self.system_prompt = prompt_path.read_text(encoding="utf-8")
        self.use_rescue = use_rescue
        self.rescue = RescueJudge(client) if use_rescue else None

    def build_request(
        self,
        transcript: Transcript,
        consensus_block: str,
        company_name: str,
        level_block: str = "",
    ) -> BatchRequestItem:
        """Build the LLM request for one quarter without making the call
        (see DimensionScorer.build_request for the batch-runner contract)."""
        user_content = _build_user_content(
            transcript, consensus_block, company_name, level_block
        )
        label = f"{transcript.ticker}_{transcript.fiscal_period}_surprise"
        return BatchRequestItem(
            custom_id=label, system_prompt=self.system_prompt, user_content=user_content
        )

    def finalize(
        self,
        summary: TranscriptSurpriseSummary,
        result: LLMResult,
        label: str,
        source_text: str,
    ) -> ScoredSurpriseTranscript:
        surprises = self._verify(summary, source_text, label)
        return ScoredSurpriseTranscript(
            summary=summary, surprises=surprises, llm_result=result
        )

    def score(
        self,
        transcript: Transcript,
        consensus_block: str,
        company_name: str,
        level_block: str = "",
    ) -> ScoredSurpriseTranscript:
        request = self.build_request(transcript, consensus_block, company_name, level_block)
        summary, result = self.client.complete_json(
            system_prompt=request.system_prompt,
            user_content=request.user_content,
            response_model=self.RESPONSE_MODEL,
            label=request.custom_id,
        )
        return self.finalize(summary, result, request.custom_id, transcript.raw_text)

    def _verify(
        self,
        summary: TranscriptSurpriseSummary,
        source_text: str,
        label: str,
    ) -> list[ScoredSurprise]:
        comparable = set(QUANT_COMPARABLE_DIMENSIONS)
        pairs: list[tuple[str, str]] = []
        spans: list[tuple[DimensionSurprise, int, int]] = []
        for s in summary.surprises:
            if s.dimension not in comparable:
                continue
            start = len(pairs)
            for ev in s.evidence:
                pairs.append((ev.claim, ev.excerpt))
            spans.append((s, start, len(pairs)))

        scored = verify_excerpts(pairs, source_text, rescue=self.rescue, label=label)

        return [
            ScoredSurprise(
                dimension=s.dimension,
                surprise_direction=s.surprise_direction,
                surprise_magnitude=round(float(s.surprise_magnitude), 1),
                rationale=s.rationale,
                is_quant_comparable=s.dimension in comparable,
                evidence=scored[start:end],
            )
            for s, start, end in spans
        ]
