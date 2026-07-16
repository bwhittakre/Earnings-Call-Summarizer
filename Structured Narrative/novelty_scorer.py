#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Focus 3b: narrative NOVELTY scorer for dimensions without consensus comparison.
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

from src.llm.anthropic_client import AnthropicClient  # noqa: E402
from src.schemas.models import EvidenceClaim, LLMResult  # noqa: E402
from src.validation.rescue_judge import RescueJudge  # noqa: E402

from dimension_scorer import NARRATIVE_ONLY_DIMENSIONS, ScoredExcerpt, verify_excerpts  # noqa: E402
from transcript_providers import Transcript  # noqa: E402

NOVELTY_PROMPT_PATH = HERE / "prompts" / "dimension_novelty.txt"

VALID_DIRECTIONS = ("high_novelty", "moderate_novelty", "low_novelty")


class DimensionNovelty(BaseModel):
    dimension: str
    novelty_direction: str = "low_novelty"
    novelty_magnitude: float = Field(0.0, ge=-2, le=2)
    evidence: list[EvidenceClaim] = Field(default_factory=list)
    rationale: str = ""

    @field_validator("novelty_direction", mode="before")
    @classmethod
    def _normalize_direction(cls, v: object) -> str:
        s = str(v or "").strip().lower().replace(" ", "_")
        if s in VALID_DIRECTIONS:
            return s
        if "high" in s or "major" in s or "new" in s:
            return "high_novelty"
        if "moderate" in s or "some" in s:
            return "moderate_novelty"
        return "low_novelty"


class TranscriptNoveltySummary(BaseModel):
    company_name: str
    ticker: str
    fiscal_period: str
    as_of_date: str | None = None
    novelties: list[DimensionNovelty] = Field(min_length=1)


@dataclass
class ScoredNovelty:
    dimension: str
    novelty_direction: str
    novelty_magnitude: float
    rationale: str
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
class ScoredNoveltyTranscript:
    summary: TranscriptNoveltySummary
    novelties: list[ScoredNovelty]
    llm_result: LLMResult

    @property
    def n_excerpts(self) -> int:
        return sum(n.n_evidence for n in self.novelties)

    @property
    def n_excerpts_verified(self) -> int:
        return sum(n.n_evidence_verified for n in self.novelties)


def _build_user_content(
    transcript: Transcript,
    prior_block: str,
    company_name: str,
) -> str:
    parts = [
        f"Company: {company_name}",
        f"Ticker: {transcript.ticker}",
        f"Fiscal period: {transcript.fiscal_period}",
    ]
    if transcript.call_date:
        parts.append(f"Call date (as-of): {transcript.call_date}")
    parts.append(
        "Score narrative NOVELTY vs the prior quarter only. Do not score vs consensus."
    )
    parts.append("")
    parts.append("--- PRIOR QUARTER SUMMARY ---")
    parts.append(prior_block)
    parts.append("")
    parts.append("--- EARNINGS CALL TRANSCRIPT (current quarter) ---")
    parts.append(transcript.raw_text)
    return "\n".join(parts)


class NoveltyScorer:
    def __init__(
        self,
        client: AnthropicClient,
        prompt_path: Path = NOVELTY_PROMPT_PATH,
        use_rescue: bool = True,
    ):
        self.client = client
        self.system_prompt = prompt_path.read_text(encoding="utf-8")
        self.use_rescue = use_rescue
        self.rescue = RescueJudge(client) if use_rescue else None

    def score(
        self,
        transcript: Transcript,
        prior_block: str,
        company_name: str,
    ) -> ScoredNoveltyTranscript:
        user_content = _build_user_content(transcript, prior_block, company_name)
        label = f"{transcript.ticker}_{transcript.fiscal_period}_novelty"
        summary, result = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=TranscriptNoveltySummary,
            label=label,
        )
        novelties = self._verify(summary, transcript.raw_text, label)
        return ScoredNoveltyTranscript(
            summary=summary, novelties=novelties, llm_result=result
        )

    def _verify(
        self,
        summary: TranscriptNoveltySummary,
        source_text: str,
        label: str,
    ) -> list[ScoredNovelty]:
        allowed = set(NARRATIVE_ONLY_DIMENSIONS)
        pairs: list[tuple[str, str]] = []
        spans: list[tuple[DimensionNovelty, int, int]] = []
        for n in summary.novelties:
            if n.dimension not in allowed:
                continue
            start = len(pairs)
            for ev in n.evidence:
                pairs.append((ev.claim, ev.excerpt))
            spans.append((n, start, len(pairs)))

        scored = verify_excerpts(pairs, source_text, rescue=self.rescue, label=label)

        return [
            ScoredNovelty(
                dimension=n.dimension,
                novelty_direction=n.novelty_direction,
                novelty_magnitude=round(float(n.novelty_magnitude), 1),
                rationale=n.rationale,
                evidence=scored[start:end],
            )
            for n, start, end in spans
        ]
