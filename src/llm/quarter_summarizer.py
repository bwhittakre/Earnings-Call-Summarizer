from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from src.llm.anthropic_client import AnthropicClient, load_prompt
from src.schemas.models import (
    AnalysisRepairResponse,
    EvidenceBackedQuarterSummary,
    LLMResult,
    QuarterSummary,
    quarter_summary_from_evidence,
)
from src.scoring.analysis_score import apply_confidence_score_from_analysis, parse_analysis_weight
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
    backfilled_from_analysis: list[str] | None = None
    evidence_audit_path: Path | None = None


class QuarterSummarizer:
    def __init__(
        self,
        client: AnthropicClient,
        skip_rescue_judge: bool = False,
        use_batch_prompt: bool = False,
        skip_analysis_repair: bool = False,
    ):
        self.client = client
        prompt_name = "quarter_batch.txt" if use_batch_prompt else "quarter.txt"
        self.system_prompt = load_prompt(prompt_name)
        self.skip_rescue_judge = skip_rescue_judge
        self.use_batch_prompt = use_batch_prompt
        self.skip_analysis_repair = skip_analysis_repair
        self._rescue_judge: RescueJudge | None = None

    @property
    def rescue_judge(self) -> RescueJudge:
        if self._rescue_judge is None:
            self._rescue_judge = RescueJudge(self.client)
        return self._rescue_judge

    def _analysis_needs_repair(self, evidence: EvidenceBackedQuarterSummary) -> bool:
        weighted = sum(
            1 for item in evidence.analysis if parse_analysis_weight(item.claim) is not None
        )
        return len(evidence.analysis) < 4 or weighted == 0

    def _repair_analysis(
        self,
        evidence: EvidenceBackedQuarterSummary,
        corpus_text: str,
        price_block_text: str | None,
        label: str,
        dropped_analysis: list[str],
    ) -> EvidenceBackedQuarterSummary:
        sections = [
            f"Quarter: {evidence.quarter}",
            "The previous analysis bullets failed validation or were incomplete.",
            "Return corrected analysis bullets only; excerpts must be verbatim from the corpus.",
        ]
        if dropped_analysis:
            sections.append("Dropped or invalid bullets:")
            sections.extend(f"- {line}" for line in dropped_analysis)
        if price_block_text:
            sections.extend(["", price_block_text])
        sections.extend(["", "--- DOCUMENT CORPUS ---", corpus_text])
        user_content = "\n".join(sections)

        repair, _ = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=AnalysisRepairResponse,
            label=f"{label}_analysis_repair",
        )
        return evidence.model_copy(update={"analysis": repair.analysis})

    def summarize(
        self,
        quarter: str,
        source_text: str | None = None,
        label: str = "",
        price_block_text: str | None = None,
        *,
        transcript_text: str | None = None,
    ) -> tuple[ValidatedQuarterOutput, LLMResult]:
        corpus_text = source_text if source_text is not None else transcript_text
        if not corpus_text:
            raise TypeError("summarize() requires source_text or transcript_text")
        sections = [f"Quarter: {quarter}"]
        if price_block_text:
            sections.extend(["", price_block_text])
        sections.extend(["", "--- DOCUMENT CORPUS ---", corpus_text])
        user_content = "\n".join(sections)

        evidence, result = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=EvidenceBackedQuarterSummary,
            label=label,
        )
        evidence.quarter = quarter

        processed = self._process_evidence(
            evidence,
            corpus_text,
            price_block_text,
            label,
        )

        if (
            self.use_batch_prompt
            and not self.skip_analysis_repair
            and self._analysis_needs_repair(processed.evidence)
        ):
            dropped_lines = [
                f"{entry.claim} ({entry.reason})"
                for entry in processed.dropped
                if entry.field == "analysis"
            ]
            repaired = self._repair_analysis(
                processed.evidence,
                corpus_text,
                price_block_text,
                label,
                dropped_lines,
            )
            processed = self._process_evidence(
                repaired,
                corpus_text,
                price_block_text,
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
        return (
            ValidatedQuarterOutput(
                summary=summary,
                evidence=final_evidence,
                backfilled_from_analysis=list(processed.backfilled_from_analysis),
                evidence_audit_path=audit_path,
            ),
            result,
        )

    def _process_evidence(
        self,
        evidence: EvidenceBackedQuarterSummary,
        corpus_text: str,
        price_block_text: str | None,
        label: str,
    ):
        if self.skip_rescue_judge:
            return process_quarter_evidence_strict(
                evidence,
                corpus_text,
                price_block_text,
            )
        return process_quarter_evidence_with_rescue(
            evidence,
            corpus_text,
            self.rescue_judge,
            label,
            price_block_text,
        )
