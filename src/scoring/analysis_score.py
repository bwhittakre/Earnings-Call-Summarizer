from __future__ import annotations

"""Confidence score is the sum of signed analysis weights.

Weights may come from filing-backed bullets or optional [price] trend bullets
when prior-quarter stock prices were provided in the prompt.
"""

import re

from src.schemas.models import EvidenceBackedQuarterSummary, EvidenceClaim

ANALYSIS_WEIGHT_PATTERN = re.compile(r"^([+-]?\d+)\s*:")


def is_price_trend_bullet(claim: str) -> bool:
    return "[price]" in claim.lower()


def parse_analysis_weight(claim: str) -> int | None:
    match = ANALYSIS_WEIGHT_PATTERN.match(claim.strip())
    if not match:
        return None
    return int(match.group(1))


def _clamp_confidence_score(total: int) -> int:
    return max(-100, min(100, total))


def _sum_analysis_weights(
    analysis: list[EvidenceClaim],
    *,
    include_price_bullets: bool = True,
) -> int:
    total = 0
    for item in analysis:
        if not include_price_bullets and is_price_trend_bullet(item.claim):
            continue
        weight = parse_analysis_weight(item.claim)
        if weight is not None:
            total += weight
    return total


def compute_confidence_score_from_analysis(analysis: list[EvidenceClaim]) -> int:
    return _clamp_confidence_score(_sum_analysis_weights(analysis))


def compute_document_only_confidence_score(analysis: list[EvidenceClaim]) -> int:
    return _clamp_confidence_score(
        _sum_analysis_weights(analysis, include_price_bullets=False)
    )


def compute_transcript_only_confidence_score(analysis: list[EvidenceClaim]) -> int:
    return compute_document_only_confidence_score(analysis)


def filter_valid_price_bullets(
    bullets: list[EvidenceClaim],
    price_block_text: str,
) -> list[EvidenceClaim]:
    from src.validation.evidence_validator import excerpt_found_in_source

    valid: list[EvidenceClaim] = []
    for item in bullets:
        if not is_price_trend_bullet(item.claim):
            continue
        if parse_analysis_weight(item.claim) is None:
            continue
        if excerpt_found_in_source(item.excerpt, price_block_text):
            valid.append(item)
    return valid


def append_price_bullets_to_analysis(
    analysis: list[EvidenceClaim],
    price_bullets: list[EvidenceClaim],
) -> list[EvidenceClaim]:
    filing_analysis = [
        item for item in analysis if not is_price_trend_bullet(item.claim)
    ]
    return filing_analysis + list(price_bullets)


def apply_confidence_score_from_analysis(
    evidence: EvidenceBackedQuarterSummary,
) -> EvidenceBackedQuarterSummary:
    computed = compute_confidence_score_from_analysis(evidence.analysis)
    if computed == evidence.confidence_score:
        return evidence
    return evidence.model_copy(update={"confidence_score": computed})
