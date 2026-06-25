from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from src.schemas.models import (
    ConfidenceEvidence,
    EvidenceBackedQuarterSummary,
    EvidenceBackedRollupSummary,
    EvidenceClaim,
    RescueJudgeResult,
    RescueReview,
)
from src.validation.evidence_validator import (
    ValidationFailure,
    ValidationResult,
    _ensure_what_happened,
    _resolve_confidence,
    excerpt_found_in_source,
    filter_quarter_evidence,
    filter_rollup_evidence,
    validate_quarter_evidence,
    validate_rollup_evidence,
)
from src.validation.quote_anchor import find_verbatim_quote

EVIDENCE_AUDIT_DIR = (
    Path(__file__).resolve().parent.parent.parent / "output" / "evidence_audit"
)

DropStage = Literal["judge_rejected", "canonical_failed_verbatim", "missing_review"]
QUOTE_ANCHOR_REASON = "programmatic quote anchor"


@dataclass
class RescuedEntry:
    field: str
    index: int | None
    claim: str
    original_excerpt: str
    canonical_excerpt: str
    reason: str


@dataclass
class DroppedEntry:
    field: str
    index: int | None
    claim: str
    excerpt: str
    reason: str
    verdict: str | None = None
    canonical_excerpt: str | None = None
    drop_stage: DropStage | None = None


@dataclass
class EvidenceProcessingResult:
    evidence: EvidenceBackedQuarterSummary | EvidenceBackedRollupSummary
    verbatim_kept: int
    rescued: list[RescuedEntry] = field(default_factory=list)
    dropped: list[DroppedEntry] = field(default_factory=list)


def _review_key(field: str, index: int | None) -> tuple[str, int | None]:
    return field, index


def _build_review_map(reviews: list[RescueReview]) -> dict[tuple[str, int | None], RescueReview]:
    return {_review_key(review.field, review.index): review for review in reviews}


def _resolve_drop_stage(review: RescueReview | None) -> DropStage:
    if review is None:
        return "missing_review"
    if review.verdict == "drop":
        return "judge_rejected"
    return "canonical_failed_verbatim"


def _try_quote_anchor_rescue(
    field_name: str,
    index: int | None,
    claim: EvidenceClaim,
    review: RescueReview | None,
    source: str,
    rescued: list[RescuedEntry],
) -> EvidenceClaim | None:
    if not review or review.verdict != "rescued":
        return None

    hints: list[str] = [claim.excerpt]
    if review.canonical_excerpt:
        hints.append(review.canonical_excerpt)

    anchored: str | None = None
    for hint in hints:
        anchored = find_verbatim_quote(claim.claim, source, hint_excerpt=hint)
        if anchored:
            break

    if not anchored:
        return None

    rescued.append(
        RescuedEntry(
            field=field_name,
            index=index,
            claim=claim.claim,
            original_excerpt=claim.excerpt,
            canonical_excerpt=anchored,
            reason=QUOTE_ANCHOR_REASON,
        )
    )
    return EvidenceClaim(claim=claim.claim, excerpt=anchored)


def _process_claim_list(
    field_name: str,
    claims: list[EvidenceClaim],
    source: str,
    review_map: dict[tuple[str, int | None], RescueReview],
    rescued: list[RescuedEntry],
    dropped: list[DroppedEntry],
) -> tuple[list[EvidenceClaim], int]:
    kept: list[EvidenceClaim] = []
    verbatim_kept = 0

    for index, claim in enumerate(claims):
        if excerpt_found_in_source(claim.excerpt, source):
            kept.append(claim)
            verbatim_kept += 1
            continue

        review = review_map.get(_review_key(field_name, index))
        if (
            review
            and review.verdict == "rescued"
            and review.canonical_excerpt
            and excerpt_found_in_source(review.canonical_excerpt, source)
        ):
            kept.append(
                EvidenceClaim(claim=claim.claim, excerpt=review.canonical_excerpt)
            )
            rescued.append(
                RescuedEntry(
                    field=field_name,
                    index=index,
                    claim=claim.claim,
                    original_excerpt=claim.excerpt,
                    canonical_excerpt=review.canonical_excerpt,
                    reason=review.reason,
                )
            )
            continue

        anchored_claim = _try_quote_anchor_rescue(
            field_name, index, claim, review, source, rescued
        )
        if anchored_claim:
            kept.append(anchored_claim)
            continue

        reason = review.reason if review else "missing rescue review"
        dropped.append(
            DroppedEntry(
                field=field_name,
                index=index,
                claim=claim.claim,
                excerpt=claim.excerpt,
                reason=reason,
                verdict=review.verdict if review else None,
                canonical_excerpt=review.canonical_excerpt if review else None,
                drop_stage=_resolve_drop_stage(review),
            )
        )

    return kept, verbatim_kept


def _process_confidence(
    confidence: ConfidenceEvidence,
    original_confidence: ConfidenceEvidence,
    source: str,
    review_map: dict[tuple[str, int | None], RescueReview],
    rescued: list[RescuedEntry],
    dropped: list[DroppedEntry],
) -> tuple[ConfidenceEvidence, int, bool]:
    if excerpt_found_in_source(confidence.excerpt, source):
        return confidence, 1, False

    review = review_map.get(_review_key("confidence", None))
    if (
        review
        and review.verdict == "rescued"
        and review.canonical_excerpt
        and excerpt_found_in_source(review.canonical_excerpt, source)
    ):
        rescued.append(
            RescuedEntry(
                field="confidence",
                index=None,
                claim=confidence.level,
                original_excerpt=original_confidence.excerpt,
                canonical_excerpt=review.canonical_excerpt,
                reason=review.reason,
            )
        )
        return (
            ConfidenceEvidence(
                level=confidence.level,
                excerpt=review.canonical_excerpt,
            ),
            0,
            False,
        )

    hint_claim = EvidenceClaim(claim=confidence.level, excerpt=confidence.excerpt)
    anchored_claim = _try_quote_anchor_rescue(
        "confidence", None, hint_claim, review, source, rescued
    )
    if anchored_claim:
        return (
            ConfidenceEvidence(
                level=confidence.level,
                excerpt=anchored_claim.excerpt,
            ),
            0,
            False,
        )

    reason = review.reason if review else "missing rescue review"
    dropped.append(
        DroppedEntry(
            field="confidence",
            index=None,
            claim=confidence.level,
            excerpt=confidence.excerpt,
            reason=reason,
            verdict=review.verdict if review else None,
            canonical_excerpt=review.canonical_excerpt if review else None,
            drop_stage=_resolve_drop_stage(review),
        )
    )
    return confidence, 0, True


def apply_rescue_reviews_to_quarter(
    evidence: EvidenceBackedQuarterSummary,
    validation: ValidationResult,
    rescue_result: RescueJudgeResult,
    source: str,
) -> EvidenceProcessingResult:
    review_map = _build_review_map(rescue_result.reviews)
    rescued: list[RescuedEntry] = []
    dropped: list[DroppedEntry] = []
    verbatim_kept = 0

    what_happened, kept = _process_claim_list(
        "what_happened",
        evidence.what_happened,
        source,
        review_map,
        rescued,
        dropped,
    )
    verbatim_kept += kept

    positives, kept = _process_claim_list(
        "positives",
        evidence.positives,
        source,
        review_map,
        rescued,
        dropped,
    )
    verbatim_kept += kept

    negatives, kept = _process_claim_list(
        "negatives",
        evidence.negatives,
        source,
        review_map,
        rescued,
        dropped,
    )
    verbatim_kept += kept

    confidence, confidence_kept, confidence_failed = _process_confidence(
        evidence.confidence,
        evidence.confidence,
        source,
        review_map,
        rescued,
        dropped,
    )
    verbatim_kept += confidence_kept
    if confidence_failed:
        confidence = _resolve_confidence(
            evidence.confidence,
            what_happened,
            positives,
            negatives,
            source,
            confidence_failed=True,
        )

    what_happened = _ensure_what_happened(
        what_happened,
        positives,
        negatives,
        source,
    )

    filtered = EvidenceBackedQuarterSummary(
        company_name=evidence.company_name,
        quarter=evidence.quarter,
        what_happened=what_happened,
        positives=positives,
        negatives=negatives,
        confidence=confidence,
    )
    return EvidenceProcessingResult(
        evidence=filtered,
        verbatim_kept=verbatim_kept,
        rescued=rescued,
        dropped=dropped,
    )


def apply_rescue_reviews_to_rollup(
    evidence: EvidenceBackedRollupSummary,
    validation: ValidationResult,
    rescue_result: RescueJudgeResult,
    source: str,
) -> EvidenceProcessingResult:
    review_map = _build_review_map(rescue_result.reviews)
    rescued: list[RescuedEntry] = []
    dropped: list[DroppedEntry] = []
    verbatim_kept = 0

    what_happened, kept = _process_claim_list(
        "what_happened",
        evidence.what_happened,
        source,
        review_map,
        rescued,
        dropped,
    )
    verbatim_kept += kept

    positives, kept = _process_claim_list(
        "positives",
        evidence.positives,
        source,
        review_map,
        rescued,
        dropped,
    )
    verbatim_kept += kept

    negatives, kept = _process_claim_list(
        "negatives",
        evidence.negatives,
        source,
        review_map,
        rescued,
        dropped,
    )
    verbatim_kept += kept

    confidence, confidence_kept, confidence_failed = _process_confidence(
        evidence.confidence,
        evidence.confidence,
        source,
        review_map,
        rescued,
        dropped,
    )
    verbatim_kept += confidence_kept
    if confidence_failed:
        confidence = _resolve_confidence(
            evidence.confidence,
            what_happened,
            positives,
            negatives,
            source,
            confidence_failed=True,
        )

    what_happened = _ensure_what_happened(
        what_happened,
        positives,
        negatives,
        source,
    )

    filtered = EvidenceBackedRollupSummary(
        company_name=evidence.company_name,
        quarter=evidence.quarter,
        what_happened=what_happened,
        positives=positives,
        negatives=negatives,
        confidence=confidence,
    )
    return EvidenceProcessingResult(
        evidence=filtered,
        verbatim_kept=verbatim_kept,
        rescued=rescued,
        dropped=dropped,
    )


def process_quarter_evidence_strict(
    evidence: EvidenceBackedQuarterSummary,
    transcript_text: str,
) -> EvidenceProcessingResult:
    validation = validate_quarter_evidence(evidence, transcript_text)
    if validation.is_valid:
        total = (
            len(evidence.what_happened)
            + len(evidence.positives)
            + len(evidence.negatives)
            + 1
        )
        return EvidenceProcessingResult(
            evidence=evidence,
            verbatim_kept=total,
        )

    filtered = filter_quarter_evidence(evidence, validation, transcript_text)
    dropped = [
        DroppedEntry(
            field=failure.field,
            index=failure.index,
            claim=failure.claim,
            excerpt=failure.excerpt,
            reason=failure.reason,
        )
        for failure in validation.failures
    ]
    total = (
        len(evidence.what_happened)
        + len(evidence.positives)
        + len(evidence.negatives)
        + 1
    )
    return EvidenceProcessingResult(
        evidence=filtered,
        verbatim_kept=total - len(validation.failures),
        dropped=dropped,
    )


def process_rollup_evidence_strict(
    evidence: EvidenceBackedRollupSummary,
    quarter_summaries: list[EvidenceBackedQuarterSummary],
) -> EvidenceProcessingResult:
    validation = validate_rollup_evidence(evidence, quarter_summaries)
    if validation.is_valid:
        total = (
            len(evidence.what_happened)
            + len(evidence.positives)
            + len(evidence.negatives)
            + 1
        )
        return EvidenceProcessingResult(
            evidence=evidence,
            verbatim_kept=total,
        )

    filtered = filter_rollup_evidence(evidence, validation, quarter_summaries)
    dropped = [
        DroppedEntry(
            field=failure.field,
            index=failure.index,
            claim=failure.claim,
            excerpt=failure.excerpt,
            reason=failure.reason,
        )
        for failure in validation.failures
    ]
    total = (
        len(evidence.what_happened)
        + len(evidence.positives)
        + len(evidence.negatives)
        + 1
    )
    return EvidenceProcessingResult(
        evidence=filtered,
        verbatim_kept=total - len(validation.failures),
        dropped=dropped,
    )


def failures_to_review_payload(failures: list[ValidationFailure]) -> list[dict]:
    return [
        {
            "field": failure.field,
            "index": failure.index,
            "claim": failure.claim,
            "excerpt": failure.excerpt,
        }
        for failure in failures
    ]


def _serialize_dropped_entry(entry: DroppedEntry) -> dict:
    payload = {
        "field": entry.field,
        "index": entry.index,
        "claim": entry.claim,
        "excerpt": entry.excerpt,
        "reason": entry.reason,
    }
    if entry.verdict is not None:
        payload["verdict"] = entry.verdict
    if entry.canonical_excerpt is not None:
        payload["canonical_excerpt"] = entry.canonical_excerpt
    if entry.drop_stage is not None:
        payload["drop_stage"] = entry.drop_stage
    return payload


def save_evidence_audit(
    label: str,
    result: EvidenceProcessingResult,
) -> Path | None:
    if not result.rescued and not result.dropped:
        return None

    EVIDENCE_AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = re.sub(r"[^\w\-]+", "_", label)
    path = EVIDENCE_AUDIT_DIR / f"{safe_label}_{timestamp}.json"
    path.write_text(
        json.dumps(
            {
                "label": label,
                "verbatim_kept": result.verbatim_kept,
                "rescued": [
                    {
                        "field": entry.field,
                        "index": entry.index,
                        "claim": entry.claim,
                        "original_excerpt": entry.original_excerpt,
                        "canonical_excerpt": entry.canonical_excerpt,
                        "reason": entry.reason,
                    }
                    for entry in result.rescued
                ],
                "dropped": [_serialize_dropped_entry(entry) for entry in result.dropped],
                "final_claim_counts": {
                    "what_happened": len(result.evidence.what_happened),
                    "positives": len(result.evidence.positives),
                    "negatives": len(result.evidence.negatives),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
