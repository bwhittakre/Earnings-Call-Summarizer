from __future__ import annotations

import re

from src.schemas.models import EvidenceBackedQuarterSummary, EvidenceClaim

ANALYSIS_WEIGHT_PATTERN = re.compile(r"^([+-]?\d+)\s*:")


def parse_analysis_weight(claim: str) -> int | None:
    match = ANALYSIS_WEIGHT_PATTERN.match(claim.strip())
    if not match:
        return None
    return int(match.group(1))


def compute_confidence_score_from_analysis(analysis: list[EvidenceClaim]) -> int:
    total = 0
    for item in analysis:
        weight = parse_analysis_weight(item.claim)
        if weight is not None:
            total += weight
    return max(-100, min(100, total))


def apply_confidence_score_from_analysis(
    evidence: EvidenceBackedQuarterSummary,
) -> EvidenceBackedQuarterSummary:
    computed = compute_confidence_score_from_analysis(evidence.analysis)
    if computed == evidence.confidence_score:
        return evidence
    return evidence.model_copy(update={"confidence_score": computed})
