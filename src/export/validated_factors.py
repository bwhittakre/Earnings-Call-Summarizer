from __future__ import annotations

from dataclasses import dataclass

from src.schemas.models import EvidenceBackedQuarterSummary, EvidenceClaim


@dataclass(frozen=True)
class ValidatedFactorRow:
    quarter: str
    source: str
    field: str
    claim: str
    excerpt: str
    in_score: str


def _format_claim_excerpt(item: EvidenceClaim) -> tuple[str, str]:
    return item.claim, item.excerpt


def _append_filing_factors(
    rows: list[ValidatedFactorRow],
    quarter: str,
    evidence: EvidenceBackedQuarterSummary,
) -> None:
    for field, claims, in_score in (
        ("what_happened", evidence.what_happened, "No"),
        ("positives", evidence.positives, "No"),
        ("negatives", evidence.negatives, "No"),
        ("analysis", evidence.analysis, "Yes"),
    ):
        for item in claims:
            claim, excerpt = _format_claim_excerpt(item)
            rows.append(
                ValidatedFactorRow(
                    quarter=quarter,
                    source="Filing",
                    field=field,
                    claim=claim,
                    excerpt=excerpt,
                    in_score=in_score,
                )
            )


def _append_transcript_factors(
    rows: list[ValidatedFactorRow],
    quarter: str,
    enrichment,
) -> None:
    from src.enrichment.models import EnrichmentResult

    if not isinstance(enrichment, EnrichmentResult):
        return
    for field, claims in (
        ("positives", enrichment.positives),
        ("negatives", enrichment.negatives),
        ("key_quotes", enrichment.key_quotes),
    ):
        for item in claims:
            claim, excerpt = _format_claim_excerpt(item)
            rows.append(
                ValidatedFactorRow(
                    quarter=quarter,
                    source="Transcript",
                    field=field,
                    claim=claim,
                    excerpt=excerpt,
                    in_score="No",
                )
            )


def build_validated_factor_rows(results) -> list[ValidatedFactorRow]:
    from src.batch.models import BatchQuarterResult
    from src.schemas.models import EvidenceBackedQuarterSummary

    rows: list[ValidatedFactorRow] = []
    for result in results:
        if not isinstance(result, BatchQuarterResult):
            continue
        if isinstance(result.filing_evidence, EvidenceBackedQuarterSummary):
            _append_filing_factors(rows, result.quarter_label, result.filing_evidence)
        if result.enrichment is not None:
            _append_transcript_factors(rows, result.quarter_label, result.enrichment)
    return rows
