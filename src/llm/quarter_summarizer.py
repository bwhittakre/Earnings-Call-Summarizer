from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from src.ingest.call_date import format_call_date
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


def format_knowledge_cutoff_header(call_date: date) -> str:
    formatted = format_call_date(call_date)
    return (
        f"KNOWLEDGE CUTOFF: Treat {formatted} as today.\n"
        "Use ONLY the transcript and PRIOR QUARTER STOCK PRICES block below.\n"
        "Do not use information from after this date, including general world knowledge.\n"
        "If uncertain, omit rather than infer from later events."
    )


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

    def summarize(
        self,
        quarter: str,
        transcript_text: str,
        label: str,
        price_block_text: str | None = None,
        call_date: date | None = None,
    ) -> tuple[ValidatedQuarterOutput, LLMResult]:
        sections: list[str] = [f"Quarter: {quarter}"]
        if self.point_in_time.active and call_date is not None:
            sections.extend(["", format_knowledge_cutoff_header(call_date)])
        if price_block_text:
            sections.extend(["", price_block_text])
        sections.extend(["", "--- TRANSCRIPT ---", transcript_text])
        user_content = "\n".join(sections)

        evidence, result = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=EvidenceBackedQuarterSummary,
            label=label,
        )
        evidence.quarter = quarter

        if self.skip_rescue_judge:
            processed = process_quarter_evidence_strict(
                evidence,
                transcript_text,
                price_block_text,
            )
        else:
            processed = process_quarter_evidence_with_rescue(
                evidence,
                transcript_text,
                self.rescue_judge,
                label,
                price_block_text,
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
        final_evidence = apply_confidence_score_from_analysis(final_evidence)
        if final_evidence.confidence_score != processed.evidence.confidence_score:
            logger.info(
                "Adjusted confidence_score from %s to %s based on analysis weights",
                processed.evidence.confidence_score,
                final_evidence.confidence_score,
            )
        summary = quarter_summary_from_evidence(final_evidence)
        return ValidatedQuarterOutput(summary=summary, evidence=final_evidence), result
