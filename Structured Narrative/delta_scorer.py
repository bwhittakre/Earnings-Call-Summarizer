#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Focus 2: narrative DELTA (quarter-over-quarter change) scorer.
==============================================================

Given the CURRENT quarter's transcript plus the PRIOR quarter's already-extracted
dimension summary (scores + rationale + evidence, from AMZN_dimension_view.json),
this asks the LLM what CHANGED per business dimension:

  * change_direction   improved | steady | deteriorated (vs the prior quarter)
  * change_magnitude   continuous -2.0..+2.0 (one decimal; sign = direction),
                       how big/important the narrative shift is
  * rationale          one sentence naming the change
  * evidence           1-3 excerpts FROM THE CURRENT transcript showing the shift

Every excerpt is checked back against the current transcript with the SAME layered
cascade used by the level scorer (verify_excerpts: verbatim -> composite ->
anchored -> LLM paraphrase rescue), so change-evidence is labeled by status rather
than dropped.

The deterministic numeric anchors (prior/current level, score_delta, quant_z_delta)
are computed by the orchestrator (run_delta_scoring.py) from the level/quant spine;
this module owns the LLM change read + evidence verification.
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

from dimension_scorer import (  # noqa: E402
    QUANT_COMPARABLE_DIMENSIONS,
    ScoredExcerpt,
    verify_excerpts,
)
from transcript_providers import Transcript  # noqa: E402

DELTA_PROMPT_SUMMARY = HERE / "prompts" / "dimension_delta.txt"
DELTA_PROMPT_FULL = HERE / "prompts" / "dimension_delta_full.txt"

CONTEXT_SUMMARY = "summary"
CONTEXT_BOTH_TRANSCRIPTS = "both_transcripts"
VALID_CONTEXTS = frozenset({CONTEXT_SUMMARY, CONTEXT_BOTH_TRANSCRIPTS})

VALID_DIRECTIONS = ("improved", "steady", "deteriorated")


class DimensionDelta(BaseModel):
    dimension: str
    change_direction: str = "steady"
    change_magnitude: float = Field(0.0, ge=-2, le=2)  # sign = direction
    evidence: list[EvidenceClaim] = Field(default_factory=list)
    rationale: str = ""

    @field_validator("change_direction", mode="before")
    @classmethod
    def _normalize_direction(cls, v: object) -> str:
        s = str(v or "").strip().lower()
        if s in VALID_DIRECTIONS:
            return s
        # tolerate minor variants; anything unknown falls back to steady and the
        # magnitude sign (checked post-init) will still carry the signal.
        if s.startswith("improv") or s.startswith("better") or s.startswith("up"):
            return "improved"
        if s.startswith("deterior") or s.startswith("worse") or s.startswith("down"):
            return "deteriorated"
        return "steady"


class TranscriptDeltaSummary(BaseModel):
    company_name: str
    ticker: str
    fiscal_period: str            # current period
    prior_period: str | None = None
    as_of_date: str | None = None
    deltas: list[DimensionDelta] = Field(min_length=1)


@dataclass
class ScoredDelta:
    dimension: str
    change_direction: str
    change_magnitude: float
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
class ScoredDeltaTranscript:
    summary: TranscriptDeltaSummary
    deltas: list[ScoredDelta]
    llm_result: LLMResult

    @property
    def n_excerpts(self) -> int:
        return sum(d.n_evidence for d in self.deltas)

    @property
    def n_excerpts_verified(self) -> int:
        return sum(d.n_evidence_verified for d in self.deltas)


def format_prior_summary(prior_quarter: dict, max_evidence: int = 2) -> str:
    """Render a prior-quarter view entry (from AMZN_dimension_view.json) into a
    compact text baseline the delta prompt can consume."""
    lines: list[str] = []
    fp = prior_quarter.get("fiscal_period", "prior quarter")
    lines.append(f"Prior quarter: {fp}")
    for d in prior_quarter.get("dimensions", []):
        dim = d.get("dimension", "")
        score = d.get("score")
        score_str = f"{float(score):+.1f}" if isinstance(score, (int, float)) else "n/a"
        rationale = (d.get("rationale") or "").strip()
        lines.append(f"- {dim} (score {score_str}): {rationale}")
        for ev in (d.get("evidence") or [])[:max_evidence]:
            claim = (ev.get("claim") or "").strip()
            if claim:
                lines.append(f"    * {claim}")
    return "\n".join(lines)


def _build_user_content(
    current: Transcript,
    prior_period: str,
    company_name: str,
    *,
    context: str = CONTEXT_SUMMARY,
    prior_summary_block: str = "",
    prior_transcript: Transcript | None = None,
) -> str:
    parts = [
        f"Company: {company_name}",
        f"Ticker: {current.ticker}",
        f"Prior period: {prior_period}",
        f"Current period: {current.fiscal_period}",
    ]
    as_of = current.call_date or ""
    if as_of:
        parts.append(f"Current call date (as-of): {as_of}")
    pit = (
        "You may only use information stated in the transcripts below. "
        "Do not use any knowledge dated after the current call."
    )
    parts.append(pit)
    parts.append("")

    if context == CONTEXT_BOTH_TRANSCRIPTS:
        if prior_transcript is None:
            raise ValueError("prior_transcript required for both_transcripts context")
        parts.append("--- PRIOR QUARTER EARNINGS CALL TRANSCRIPT ---")
        parts.append(prior_transcript.raw_text)
        parts.append("")
        parts.append("--- CURRENT EARNINGS CALL TRANSCRIPT ---")
        parts.append(current.raw_text)
    else:
        parts.append(
            "--- PRIOR QUARTER SUMMARY (baseline of what management said last quarter) ---"
        )
        parts.append(prior_summary_block)
        parts.append("")
        parts.append("--- CURRENT EARNINGS CALL TRANSCRIPT ---")
        parts.append(current.raw_text)
    return "\n".join(parts)


class DeltaScorer:
    def __init__(
        self,
        client: AnthropicClient,
        context: str = CONTEXT_SUMMARY,
        use_rescue: bool = True,
    ):
        if context not in VALID_CONTEXTS:
            raise ValueError(f"context must be one of {sorted(VALID_CONTEXTS)}")
        self.context = context
        prompt_path = (
            DELTA_PROMPT_FULL if context == CONTEXT_BOTH_TRANSCRIPTS else DELTA_PROMPT_SUMMARY
        )
        self.client = client
        self.system_prompt = prompt_path.read_text(encoding="utf-8")
        self.use_rescue = use_rescue
        self.rescue = RescueJudge(client) if use_rescue else None

    def score(
        self,
        current: Transcript,
        prior_period: str,
        company_name: str,
        *,
        prior_summary_block: str = "",
        prior_transcript: Transcript | None = None,
    ) -> ScoredDeltaTranscript:
        user_content = _build_user_content(
            current,
            prior_period,
            company_name,
            context=self.context,
            prior_summary_block=prior_summary_block,
            prior_transcript=prior_transcript,
        )
        label = f"{current.ticker}_{prior_period}_to_{current.fiscal_period}_delta"
        summary, result = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=TranscriptDeltaSummary,
            label=label,
        )
        deltas = self._verify(summary, current.raw_text, label)
        return ScoredDeltaTranscript(summary=summary, deltas=deltas, llm_result=result)

    def _verify(
        self,
        summary: TranscriptDeltaSummary,
        source_text: str,
        label: str,
    ) -> list[ScoredDelta]:
        comparable = set(QUANT_COMPARABLE_DIMENSIONS)
        pairs: list[tuple[str, str]] = []
        spans: list[tuple[DimensionDelta, int, int]] = []
        for d in summary.deltas:
            start = len(pairs)
            for ev in d.evidence:
                pairs.append((ev.claim, ev.excerpt))
            spans.append((d, start, len(pairs)))

        scored = verify_excerpts(pairs, source_text, rescue=self.rescue, label=label)

        return [
            ScoredDelta(
                dimension=d.dimension,
                change_direction=d.change_direction,
                change_magnitude=round(float(d.change_magnitude), 1),
                rationale=d.rationale,
                is_quant_comparable=d.dimension in comparable,
                evidence=scored[start:end],
            )
            for d, start, end in spans
        ]
