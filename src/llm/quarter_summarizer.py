from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from src.ingest.dates import format_as_of_date
from src.llm.anthropic_client import AnthropicClient, load_prompt
from src.pipeline.point_in_time import PointInTimeConfig
from src.schemas.models import (
    EvidenceBackedQuarterSummary,
    LLMResult,
    QuarterSummary,
    quarter_summary_from_evidence,
)
from src.scoring.analysis_score import apply_confidence_score_from_analysis
from src.validation.evidence_processor import (
    process_quarter_evidence_strict,
    process_quarter_evidence_with_rescue,
    save_evidence_audit,
)
from src.validation.rescue_judge import RescueJudge

logger = logging.getLogger(__name__)


@dataclass
class ValidatedQuarterOutput:
    summary: QuarterSummary
    evidence: EvidenceBackedQuarterSummary


def format_knowledge_cutoff_header(as_of_date: date) -> str:
    formatted = format_as_of_date(as_of_date)
    return (
        f"KNOWLEDGE CUTOFF: Treat {formatted} as today.\n"
        "Use ONLY the filing corpus below.\n"
        "Do not use information from after this date, including general world knowledge.\n"
        "If uncertain, omit rather than infer from later events."
    )


def _build_user_content(
    *,
    quarter: str,
    corpus_text: str,
    company_name: str | None,
    is_q4: bool,
    point_in_time_active: bool,
    as_of_date: date | None,
) -> str:
    sections: list[str] = [f"Quarter: {quarter}"]
    if company_name:
        sections.append(f"Company: {company_name}")
    if is_q4:
        sections.append(
            "Package type: Q4 fiscal year-end (10-K anchor with prior Q1–Q3 10-Q cross-reference)."
        )
    if point_in_time_active and as_of_date is not None:
        sections.extend(["", format_knowledge_cutoff_header(as_of_date)])
    sections.extend(["", "--- FILINGS ---", corpus_text])
    return "\n".join(sections)


class QuarterSummarizer:
    def __init__(
        self,
        client: AnthropicClient,
        skip_rescue_judge: bool = False,
        point_in_time: PointInTimeConfig | None = None,
    ):
        self.client = client
        self.system_prompt = load_prompt("quarter.txt")
        self.skip_rescue_judge = skip_rescue_judge
        self.point_in_time = point_in_time or PointInTimeConfig.disabled()
        self.rescue_judge = RescueJudge(client)

    def _process_document_evidence(
        self,
        evidence: EvidenceBackedQuarterSummary,
        corpus_text: str,
        label: str,
    ) -> EvidenceBackedQuarterSummary:
        if self.skip_rescue_judge:
            processed = process_quarter_evidence_strict(
                evidence,
                corpus_text,
            )
        else:
            processed = process_quarter_evidence_with_rescue(
                evidence,
                corpus_text,
                self.rescue_judge,
                label,
            )

        audit_path = save_evidence_audit(label, processed)
        if processed.rescued or processed.dropped or processed.auto_anchored:
            logger.warning(
                "Evidence audit for %s: kept=%s anchored=%s rescued=%s dropped=%s audit=%s",
                label,
                processed.verbatim_kept,
                len(processed.auto_anchored),
                len(processed.rescued),
                len(processed.dropped),
                audit_path,
            )

        final_evidence = processed.evidence
        assert isinstance(final_evidence, EvidenceBackedQuarterSummary)
        return final_evidence

    def summarize(
        self,
        quarter: str,
        corpus_text: str,
        label: str,
        as_of_date: date | None = None,
        company_name: str | None = None,
        is_q4: bool = False,
    ) -> tuple[ValidatedQuarterOutput, LLMResult]:
        user_content = _build_user_content(
            quarter=quarter,
            corpus_text=corpus_text,
            company_name=company_name,
            is_q4=is_q4,
            point_in_time_active=self.point_in_time.active,
            as_of_date=as_of_date,
        )

        evidence, result = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=EvidenceBackedQuarterSummary,
            label=label,
        )
        evidence.quarter = quarter
        if company_name:
            evidence.company_name = company_name

        final_evidence = self._process_document_evidence(
            evidence,
            corpus_text,
            label,
        )
        final_evidence = apply_confidence_score_from_analysis(final_evidence)
        if final_evidence.confidence_score != evidence.confidence_score:
            logger.info(
                "Adjusted confidence_score from %s to %s based on analysis weights",
                evidence.confidence_score,
                final_evidence.confidence_score,
            )

        summary = quarter_summary_from_evidence(final_evidence)
        return ValidatedQuarterOutput(summary=summary, evidence=final_evidence), result
