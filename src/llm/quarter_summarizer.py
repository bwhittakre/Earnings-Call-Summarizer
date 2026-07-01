from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from src.ingest.dates import format_as_of_date
from src.llm.anthropic_client import AnthropicClient, load_prompt
from src.pipeline.point_in_time import PointInTimeConfig
from src.schemas.models import (
    EvidenceBackedQuarterSummary,
    EvidenceClaim,
    LLMResult,
    PriceAnalysisBullets,
    QuarterSummary,
    TokenUsage,
    quarter_summary_from_evidence,
)
from src.scoring.analysis_score import (
    append_price_bullets_to_analysis,
    apply_confidence_score_from_analysis,
    filter_valid_price_bullets,
    is_price_trend_bullet,
)
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
        "Use ONLY the filing corpus and PRIOR QUARTER STOCK PRICES block below.\n"
        "Do not use information from after this date, including general world knowledge.\n"
        "If uncertain, omit rather than infer from later events."
    )


def _combine_llm_results(first: LLMResult, second: LLMResult) -> LLMResult:
    return LLMResult(
        usage=TokenUsage(
            input_tokens=first.usage.input_tokens + second.usage.input_tokens,
            output_tokens=first.usage.output_tokens + second.usage.output_tokens,
        ),
        raw_response=second.raw_response,
    )


def _build_user_content(
    *,
    quarter: str,
    corpus_text: str,
    company_name: str | None,
    is_q4: bool,
    point_in_time_active: bool,
    as_of_date: date | None,
    price_block_text: str | None,
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
    if price_block_text:
        sections.extend(["", price_block_text])
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
        self.price_bullets_prompt = load_prompt("price_bullets.txt")
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
                None,
            )
        else:
            processed = process_quarter_evidence_with_rescue(
                evidence,
                corpus_text,
                self.rescue_judge,
                label,
                None,
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

    def _fetch_price_bullets(
        self,
        *,
        price_block_text: str,
        label: str,
        as_of_date: date | None,
    ) -> tuple[list[EvidenceClaim], LLMResult]:
        sections: list[str] = []
        if self.point_in_time.active and as_of_date is not None:
            sections.extend([format_knowledge_cutoff_header(as_of_date), ""])
        sections.append(price_block_text)
        user_content = "\n".join(sections)

        price_payload, price_result = self.client.complete_json(
            system_prompt=self.price_bullets_prompt,
            user_content=user_content,
            response_model=PriceAnalysisBullets,
            label=f"{label}_price",
        )
        valid = filter_valid_price_bullets(price_payload.analysis, price_block_text)
        dropped = len(price_payload.analysis) - len(valid)
        if dropped:
            logger.warning(
                "Dropped %s invalid [price] bullet(s) for %s",
                dropped,
                label,
            )
        return valid, price_result

    def summarize(
        self,
        quarter: str,
        corpus_text: str,
        label: str,
        price_block_text: str | None = None,
        as_of_date: date | None = None,
        company_name: str | None = None,
        is_q4: bool = False,
    ) -> tuple[ValidatedQuarterOutput, LLMResult]:
        document_user_content = _build_user_content(
            quarter=quarter,
            corpus_text=corpus_text,
            company_name=company_name,
            is_q4=is_q4,
            point_in_time_active=self.point_in_time.active,
            as_of_date=as_of_date,
            price_block_text=None,
        )

        evidence, result = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=document_user_content,
            response_model=EvidenceBackedQuarterSummary,
            label=label,
        )
        evidence.quarter = quarter
        if company_name:
            evidence.company_name = company_name

        document_evidence = self._process_document_evidence(
            evidence,
            corpus_text,
            label,
        )
        document_evidence = apply_confidence_score_from_analysis(document_evidence)
        if document_evidence.confidence_score != evidence.confidence_score:
            logger.info(
                "Adjusted document confidence_score from %s to %s based on analysis weights",
                evidence.confidence_score,
                document_evidence.confidence_score,
            )

        filing_analysis = [
            item
            for item in document_evidence.analysis
            if not is_price_trend_bullet(item.claim)
        ]
        document_evidence = document_evidence.model_copy(update={"analysis": filing_analysis})

        if price_block_text:
            price_bullets, price_result = self._fetch_price_bullets(
                price_block_text=price_block_text,
                label=label,
                as_of_date=as_of_date,
            )
            merged_analysis = append_price_bullets_to_analysis(
                document_evidence.analysis,
                price_bullets,
            )
            final_evidence = document_evidence.model_copy(
                update={"analysis": merged_analysis}
            )
            final_evidence = apply_confidence_score_from_analysis(final_evidence)
            logger.info(
                "Added %s [price] analysis bullet(s) for %s; document-only score unchanged at %s; confidence_score=%s",
                len(price_bullets),
                label,
                document_evidence.confidence_score,
                final_evidence.confidence_score,
            )
            result = _combine_llm_results(result, price_result)
        else:
            final_evidence = document_evidence

        summary = quarter_summary_from_evidence(final_evidence)
        return ValidatedQuarterOutput(summary=summary, evidence=final_evidence), result
