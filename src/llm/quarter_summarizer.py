from __future__ import annotations

import logging
from dataclasses import dataclass

from src.llm.anthropic_client import AnthropicClient, load_prompt
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


class QuarterSummarizer:
    def __init__(
        self,
        client: AnthropicClient,
        skip_rescue_judge: bool = False,
    ):
        self.client = client
        self.system_prompt = load_prompt("quarter.txt")
        self.skip_rescue_judge = skip_rescue_judge
        self.rescue_judge = RescueJudge(client)

    def summarize(
        self,
        quarter: str,
        transcript_text: str,
        label: str,
    ) -> tuple[ValidatedQuarterOutput, LLMResult]:
        user_content = (
            f"Quarter: {quarter}\n\n"
            f"--- TRANSCRIPT ---\n{transcript_text}"
        )

        evidence, result = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=EvidenceBackedQuarterSummary,
            label=label,
        )
        evidence.quarter = quarter

        if self.skip_rescue_judge:
            processed = process_quarter_evidence_strict(evidence, transcript_text)
        else:
            processed = process_quarter_evidence_with_rescue(
                evidence,
                transcript_text,
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
        final_evidence = apply_confidence_score_from_analysis(final_evidence)
        if final_evidence.confidence_score != processed.evidence.confidence_score:
            logger.info(
                "Adjusted confidence_score from %s to %s based on analysis weights",
                processed.evidence.confidence_score,
                final_evidence.confidence_score,
            )
        summary = quarter_summary_from_evidence(final_evidence)
        return ValidatedQuarterOutput(summary=summary, evidence=final_evidence), result
