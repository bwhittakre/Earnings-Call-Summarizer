#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM dimension scorer for earnings-call transcripts.
===================================================

Reuses the battle-tested LLM + evidence-validation stack from the parent
``src/`` package (``AnthropicClient`` for JSON-in/Pydantic-out, and the
normalized verbatim-substring check from ``src.validation.evidence_validator``)
rather than reinventing it.

It takes a normalized ``Transcript`` (from ``transcript_providers``) and returns
a set of per-dimension scores on a continuous -2.0..+2.0 scale (one decimal, so
the tenths capture tone intensity / how hedged management was), each with
verbatim evidence excerpts.

Every excerpt is checked back against the transcript with a layered cascade that
mirrors the confidence pipeline (rather than a single verbatim pass), so a quote
is only marked ``unverified`` when it genuinely is not supported:

  1. verbatim    exact contiguous normalized substring match.
  2. composite   an ellipsis-stitched quote whose every fragment is itself
                 verbatim in the transcript (deterministic, no LLM).
  3. anchored    a supporting contiguous verbatim span found programmatically
                 for the claim via src.validation.quote_anchor (no LLM).
  4. paraphrased the src.validation RescueJudge (LLM) rules the excerpt a
                 faithful paraphrase/shortening and returns a canonical verbatim
                 quote from the transcript.
  5. unverified  none of the above.

Nothing is ever dropped; the status is recorded so the report can reassure
rather than under-count faithful-but-non-contiguous evidence.
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.llm.anthropic_client import AnthropicClient  # noqa: E402
from src.schemas.models import EvidenceClaim, LLMResult  # noqa: E402
from src.validation.evidence_validator import (  # noqa: E402
    NormalizedSource,
    ValidationFailure,
    excerpt_found_in_source,
)
from src.validation.quote_anchor import find_verbatim_quote  # noqa: E402
from src.validation.rescue_judge import RescueJudge  # noqa: E402

from transcript_providers import Transcript  # noqa: E402

PROMPT_PATH = HERE / "prompts" / "dimension_score.txt"

# Evidence verification statuses (ordered strongest -> weakest support).
STATUS_VERBATIM = "verbatim"
STATUS_COMPOSITE = "composite"
STATUS_ANCHORED = "anchored"
STATUS_PARAPHRASED = "paraphrased"
STATUS_UNVERIFIED = "unverified"
SUPPORTED_STATUSES = frozenset(
    {STATUS_VERBATIM, STATUS_COMPOSITE, STATUS_ANCHORED, STATUS_PARAPHRASED}
)

_ELLIPSIS_RE = re.compile(r"\s*(?:\.{2,}|\u2026)\s*")
_MIN_FRAGMENT_CHARS = 15  # ignore tiny connective fragments when splitting stitches

# Dimension keys the prompt scores. The first five have a direct quant analog in
# AMZN_dimension_scores (dim_*_z); the last three are narrative-only.
QUANT_COMPARABLE_DIMENSIONS = [
    "demand",
    "margins",
    "earnings_power",
    "capital_allocation",
    "guidance",
]
NARRATIVE_ONLY_DIMENSIONS = [
    "management_confidence",
    "competitive_position",
    "macro_regulatory_risk",
]
ALL_DIMENSIONS = QUANT_COMPARABLE_DIMENSIONS + NARRATIVE_ONLY_DIMENSIONS


class DimensionScore(BaseModel):
    dimension: str
    score: float = Field(ge=-2, le=2)   # one-decimal scale; tenths encode tone intensity
    evidence: list[EvidenceClaim] = Field(default_factory=list)
    rationale: str = ""


class TranscriptDimensionSummary(BaseModel):
    company_name: str
    ticker: str
    fiscal_period: str
    as_of_date: str | None = None
    dimensions: list[DimensionScore] = Field(min_length=1)


@dataclass
class ScoredExcerpt:
    claim: str
    excerpt: str
    status: str  # one of STATUS_* above
    canonical: str | None = None  # resolved verbatim quote (anchored/paraphrased)

    @property
    def verified(self) -> bool:
        # "verified" now means "supported by the transcript", not just verbatim.
        return self.status in SUPPORTED_STATUSES


@dataclass
class ScoredDimension:
    dimension: str
    score: float
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
        # True iff every excerpt is supported (vacuously True if none).
        return all(e.verified for e in self.evidence) if self.evidence else True

    @property
    def excerpts(self) -> list[str]:
        return [e.excerpt for e in self.evidence]


@dataclass
class ScoredTranscript:
    summary: TranscriptDimensionSummary
    dimensions: list[ScoredDimension]
    llm_result: LLMResult

    @property
    def n_excerpts(self) -> int:
        return sum(d.n_evidence for d in self.dimensions)

    @property
    def n_excerpts_verified(self) -> int:
        return sum(d.n_evidence_verified for d in self.dimensions)


def _build_user_content(transcript: Transcript, company_name: str) -> str:
    parts = [
        f"Company: {company_name}",
        f"Ticker: {transcript.ticker}",
        f"Fiscal period: {transcript.fiscal_period}",
    ]
    if transcript.call_date:
        parts.append(f"Call date (as-of): {transcript.call_date}")
        parts.append(
            "You may only use information stated in the transcript below. "
            "Do not use any knowledge dated after the call."
        )
    parts.append("")
    parts.append("--- EARNINGS CALL TRANSCRIPT ---")
    parts.append(transcript.raw_text)
    return "\n".join(parts)


def _deterministic_status(
    claim: str, excerpt: str, source: NormalizedSource
) -> tuple[str, str | None]:
    """Return (status, canonical) using only non-LLM checks.

    Falls back to STATUS_UNVERIFIED (caller may then try the LLM rescue judge).
    """
    if excerpt_found_in_source(excerpt, source.text, normalized_source=source):
        return STATUS_VERBATIM, None

    # Composite: an ellipsis-stitched quote whose every (non-trivial) fragment
    # is itself verbatim in the transcript. Each piece is a real quote; the
    # model merely joined non-adjacent spans with "...".
    fragments = [
        frag.strip()
        for frag in _ELLIPSIS_RE.split(excerpt)
        if len(frag.strip()) >= _MIN_FRAGMENT_CHARS
    ]
    if len(fragments) >= 2 and all(
        excerpt_found_in_source(frag, source.text, normalized_source=source)
        for frag in fragments
    ):
        return STATUS_COMPOSITE, None

    # Anchored: programmatically locate a supporting contiguous verbatim span
    # for the claim (same pre-rescue step the confidence pipeline uses).
    anchored = find_verbatim_quote(claim, source.text, hint_excerpt=excerpt)
    if anchored:
        return STATUS_ANCHORED, anchored

    return STATUS_UNVERIFIED, None


def _apply_rescue(
    scored: list[ScoredExcerpt],
    pending: list[int],
    source: NormalizedSource,
    label: str,
    rescue: RescueJudge,
) -> None:
    """Batch remaining failures through the LLM RescueJudge (paraphrase check).

    The judge uses `field` to carry the index into `scored`; a `rescued`
    verdict whose canonical_excerpt verifies verbatim promotes the excerpt to
    STATUS_PARAPHRASED. Best-effort: any failure leaves items as unverified.
    """
    failures = [
        ValidationFailure(
            field=str(idx),
            index=0,
            claim=scored[idx].claim,
            excerpt=scored[idx].excerpt,
            reason="not a contiguous verbatim quote",
        )
        for idx in pending
    ]
    try:
        rescue_result, _ = rescue.review_failures(failures, source.text, label)
    except Exception:
        return

    review_map = {r.field: r for r in rescue_result.reviews}
    for idx in pending:
        review = review_map.get(str(idx))
        if not review or review.verdict != "rescued":
            continue
        canonical = review.canonical_excerpt
        if canonical and excerpt_found_in_source(
            canonical, source.text, normalized_source=source
        ):
            scored[idx].status = STATUS_PARAPHRASED
            scored[idx].canonical = canonical


def verify_excerpts(
    pairs: list[tuple[str, str]],
    source_text: str,
    rescue: RescueJudge | None = None,
    label: str = "",
) -> list[ScoredExcerpt]:
    """Verify (claim, excerpt) pairs against a source with the layered cascade.

    Runs the deterministic checks (verbatim -> composite -> anchored) on every
    pair, then batches all remaining failures through the LLM RescueJudge in a
    single call (paraphrase check). Returns one ScoredExcerpt per input pair,
    in order. Shared by the level scorer and the delta scorer so both label
    evidence identically.
    """
    source = NormalizedSource.from_text(source_text)
    scored: list[ScoredExcerpt] = []
    pending: list[int] = []
    for claim, excerpt in pairs:
        status, canonical = _deterministic_status(claim, excerpt, source)
        if status == STATUS_UNVERIFIED:
            pending.append(len(scored))
        scored.append(
            ScoredExcerpt(claim=claim, excerpt=excerpt, status=status, canonical=canonical)
        )
    if rescue and pending:
        _apply_rescue(scored, pending, source, label, rescue)
    return scored


class DimensionScorer:
    def __init__(
        self,
        client: AnthropicClient,
        prompt_path: Path = PROMPT_PATH,
        use_rescue: bool = True,
    ):
        self.client = client
        self.system_prompt = prompt_path.read_text(encoding="utf-8")
        # The paraphrase checker reuses the confidence pipeline's RescueJudge on the
        # SAME client so its tokens roll into the shared usage summary.
        self.use_rescue = use_rescue
        self.rescue = RescueJudge(client) if use_rescue else None

    def score(self, transcript: Transcript, company_name: str) -> ScoredTranscript:
        user_content = _build_user_content(transcript, company_name)
        label = f"{transcript.ticker}_{transcript.fiscal_period}_dimensions"
        summary, result = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=TranscriptDimensionSummary,
            label=label,
        )
        dimensions = self._verify(summary, transcript.raw_text, label)
        return ScoredTranscript(
            summary=summary, dimensions=dimensions, llm_result=result
        )

    def _verify(
        self,
        summary: TranscriptDimensionSummary,
        source_text: str,
        label: str,
    ) -> list[ScoredDimension]:
        comparable = set(QUANT_COMPARABLE_DIMENSIONS)
        pairs: list[tuple[str, str]] = []
        dim_spans: list[tuple[str, float, str, bool, int, int]] = []
        for dim in summary.dimensions:
            start = len(pairs)
            for ev in dim.evidence:
                pairs.append((ev.claim, ev.excerpt))
            dim_spans.append(
                (
                    dim.dimension,
                    round(float(dim.score), 1),
                    dim.rationale,
                    dim.dimension in comparable,
                    start,
                    len(pairs),
                )
            )

        scored = verify_excerpts(pairs, source_text, rescue=self.rescue, label=label)

        return [
            ScoredDimension(
                dimension=name,
                score=score,
                rationale=rationale,
                is_quant_comparable=is_comp,
                evidence=scored[start:end],
            )
            for name, score, rationale, is_comp, start, end in dim_spans
        ]
