from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from src.schemas.models import (
    ConfidenceEvidence,
    EvidenceBackedQuarterSummary,
    EvidenceBackedRollupSummary,
    EvidenceClaim,
)

QUARANTINE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "output" / "quarantine"
)
DROPPED_EVIDENCE_DIR = (
    Path(__file__).resolve().parent.parent.parent / "output" / "dropped_evidence"
)
MIN_EXCERPT_LENGTH = 20


@dataclass
class ValidationFailure:
    field: str
    index: int | None
    claim: str
    excerpt: str
    reason: str


@dataclass
class ValidationResult:
    is_valid: bool
    failures: list[ValidationFailure] = field(default_factory=list)

    def error_message(self) -> str:
        lines = [
            "Evidence validation failed. Every excerpt must be a verbatim contiguous quote from the allowed source text.",
        ]
        for failure in self.failures:
            location = failure.field
            if failure.index is not None:
                location = f"{failure.field}[{failure.index}]"
            lines.append(
                f"- {location}: {failure.reason}\n"
                f"  claim: {failure.claim!r}\n"
                f"  excerpt: {failure.excerpt!r}"
            )
        return "\n".join(lines)


def normalize_text(text: str) -> str:
    normalized = text.lower()
    normalized = normalized.replace("\u2019", "'").replace("\u2018", "'")
    normalized = normalized.replace("\u201c", '"').replace("\u201d", '"')
    normalized = normalized.replace("\u2013", "-").replace("\u2014", "-")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def excerpt_found_in_source(excerpt: str, source: str) -> bool:
    normalized_excerpt = normalize_text(excerpt)
    if len(normalized_excerpt) < MIN_EXCERPT_LENGTH:
        return False
    return normalized_excerpt in normalize_text(source)


def _validate_claims(
    field_name: str,
    claims: list[EvidenceClaim],
    source: str,
) -> list[ValidationFailure]:
    failures: list[ValidationFailure] = []
    for index, item in enumerate(claims):
        if not excerpt_found_in_source(item.excerpt, source):
            failures.append(
                ValidationFailure(
                    field=field_name,
                    index=index,
                    claim=item.claim,
                    excerpt=item.excerpt,
                    reason="excerpt not found in source text",
                )
            )
    return failures


def _validate_confidence(
    confidence: ConfidenceEvidence,
    source: str,
) -> list[ValidationFailure]:
    if excerpt_found_in_source(confidence.excerpt, source):
        return []
    return [
        ValidationFailure(
            field="confidence",
            index=None,
            claim=confidence.level,
            excerpt=confidence.excerpt,
            reason="confidence excerpt not found in source text",
        )
    ]


def validate_quarter_evidence(
    evidence: EvidenceBackedQuarterSummary,
    transcript_text: str,
) -> ValidationResult:
    failures: list[ValidationFailure] = []
    failures.extend(_validate_claims("what_happened", evidence.what_happened, transcript_text))
    failures.extend(_validate_claims("positives", evidence.positives, transcript_text))
    failures.extend(_validate_claims("negatives", evidence.negatives, transcript_text))
    failures.extend(_validate_confidence(evidence.confidence, transcript_text))
    return ValidationResult(is_valid=not failures, failures=failures)


def build_quarter_evidence_corpus(
    quarter_summaries: list[EvidenceBackedQuarterSummary],
) -> str:
    excerpts: list[str] = []
    for summary in quarter_summaries:
        for claims in (
            summary.what_happened,
            summary.positives,
            summary.negatives,
        ):
            excerpts.extend(item.excerpt for item in claims)
        excerpts.append(summary.confidence.excerpt)
    return "\n".join(excerpts)


def validate_rollup_evidence(
    evidence: EvidenceBackedRollupSummary,
    quarter_summaries: list[EvidenceBackedQuarterSummary],
) -> ValidationResult:
    source = build_quarter_evidence_corpus(quarter_summaries)
    failures: list[ValidationFailure] = []
    failures.extend(_validate_claims("what_happened", evidence.what_happened, source))
    failures.extend(_validate_claims("positives", evidence.positives, source))
    failures.extend(_validate_claims("negatives", evidence.negatives, source))
    failures.extend(_validate_confidence(evidence.confidence, source))
    return ValidationResult(is_valid=not failures, failures=failures)


def _failed_indices(failures: list[ValidationFailure], field_name: str) -> set[int]:
    return {
        failure.index
        for failure in failures
        if failure.field == field_name and failure.index is not None
    }


def _confidence_failed(failures: list[ValidationFailure]) -> bool:
    return any(failure.field == "confidence" for failure in failures)


def _filter_claim_list(
    claims: list[EvidenceClaim],
    failed_indices: set[int],
) -> list[EvidenceClaim]:
    return [claim for index, claim in enumerate(claims) if index not in failed_indices]


def _first_valid_claim_excerpt(
    claims: list[EvidenceClaim],
    source: str,
) -> str | None:
    for claim in claims:
        if excerpt_found_in_source(claim.excerpt, source):
            return claim.excerpt
    return None


def _fallback_transcript_excerpt(source: str) -> str:
    collapsed = re.sub(r"\s+", " ", source.strip())
    if len(collapsed) >= MIN_EXCERPT_LENGTH:
        return collapsed[: max(MIN_EXCERPT_LENGTH, min(120, len(collapsed)))]
    return collapsed.ljust(MIN_EXCERPT_LENGTH, ".")


def _ensure_what_happened(
    what_happened: list[EvidenceClaim],
    positives: list[EvidenceClaim],
    negatives: list[EvidenceClaim],
    source: str,
) -> list[EvidenceClaim]:
    if what_happened:
        return what_happened

    for candidate in positives + negatives:
        if excerpt_found_in_source(candidate.excerpt, source):
            return [candidate]

    return [
        EvidenceClaim(
            claim="Limited validated summary",
            excerpt=_fallback_transcript_excerpt(source),
        )
    ]


def _resolve_confidence(
    confidence: ConfidenceEvidence,
    what_happened: list[EvidenceClaim],
    positives: list[EvidenceClaim],
    negatives: list[EvidenceClaim],
    source: str,
    confidence_failed: bool,
) -> ConfidenceEvidence:
    if not confidence_failed:
        return confidence

    fallback_excerpt = _first_valid_claim_excerpt(
        what_happened + positives + negatives,
        source,
    )
    if fallback_excerpt is None:
        fallback_excerpt = _fallback_transcript_excerpt(source)
    return ConfidenceEvidence(level=confidence.level, excerpt=fallback_excerpt)


def filter_quarter_evidence(
    evidence: EvidenceBackedQuarterSummary,
    validation: ValidationResult,
    transcript_text: str,
) -> EvidenceBackedQuarterSummary:
    what_happened = _filter_claim_list(
        evidence.what_happened,
        _failed_indices(validation.failures, "what_happened"),
    )
    positives = _filter_claim_list(
        evidence.positives,
        _failed_indices(validation.failures, "positives"),
    )
    negatives = _filter_claim_list(
        evidence.negatives,
        _failed_indices(validation.failures, "negatives"),
    )
    what_happened = _ensure_what_happened(
        what_happened,
        positives,
        negatives,
        transcript_text,
    )
    confidence = _resolve_confidence(
        evidence.confidence,
        what_happened,
        positives,
        negatives,
        transcript_text,
        _confidence_failed(validation.failures),
    )
    return EvidenceBackedQuarterSummary(
        company_name=evidence.company_name,
        quarter=evidence.quarter,
        what_happened=what_happened,
        positives=positives,
        negatives=negatives,
        confidence=confidence,
    )


def filter_rollup_evidence(
    evidence: EvidenceBackedRollupSummary,
    validation: ValidationResult,
    quarter_summaries: list[EvidenceBackedQuarterSummary],
) -> EvidenceBackedRollupSummary:
    source = build_quarter_evidence_corpus(quarter_summaries)
    what_happened = _filter_claim_list(
        evidence.what_happened,
        _failed_indices(validation.failures, "what_happened"),
    )
    positives = _filter_claim_list(
        evidence.positives,
        _failed_indices(validation.failures, "positives"),
    )
    negatives = _filter_claim_list(
        evidence.negatives,
        _failed_indices(validation.failures, "negatives"),
    )
    what_happened = _ensure_what_happened(
        what_happened,
        positives,
        negatives,
        source,
    )
    confidence = _resolve_confidence(
        evidence.confidence,
        what_happened,
        positives,
        negatives,
        source,
        _confidence_failed(validation.failures),
    )
    return EvidenceBackedRollupSummary(
        company_name=evidence.company_name,
        quarter=evidence.quarter,
        what_happened=what_happened,
        positives=positives,
        negatives=negatives,
        confidence=confidence,
    )


def save_quarantine_artifact(
    label: str,
    payload: EvidenceBackedQuarterSummary | EvidenceBackedRollupSummary,
    validation: ValidationResult,
    raw_response: str,
) -> Path:
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = re.sub(r"[^\w\-]+", "_", label)
    path = QUARANTINE_DIR / f"{safe_label}_{timestamp}.json"
    path.write_text(
        json.dumps(
            {
                "label": label,
                "validation_errors": validation.error_message(),
                "failures": [
                    {
                        "field": failure.field,
                        "index": failure.index,
                        "claim": failure.claim,
                        "excerpt": failure.excerpt,
                        "reason": failure.reason,
                    }
                    for failure in validation.failures
                ],
                "payload": payload.model_dump(),
                "raw_response": raw_response,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def save_dropped_evidence_audit(
    label: str,
    validation: ValidationResult,
    filtered: EvidenceBackedQuarterSummary | EvidenceBackedRollupSummary,
) -> Path | None:
    if not validation.failures:
        return None

    DROPPED_EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_label = re.sub(r"[^\w\-]+", "_", label)
    path = DROPPED_EVIDENCE_DIR / f"{safe_label}_{timestamp}.json"
    path.write_text(
        json.dumps(
            {
                "label": label,
                "dropped_count": len(validation.failures),
                "dropped": [
                    {
                        "field": failure.field,
                        "index": failure.index,
                        "claim": failure.claim,
                        "excerpt": failure.excerpt,
                        "reason": failure.reason,
                    }
                    for failure in validation.failures
                ],
                "final_claim_counts": {
                    "what_happened": len(filtered.what_happened),
                    "positives": len(filtered.positives),
                    "negatives": len(filtered.negatives),
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return path
