from __future__ import annotations

import json
import logging

from src.llm.anthropic_client import AnthropicClient, load_prompt
from src.llm.quarter_summarizer import ValidatedQuarterOutput
from src.schemas.models import (
    EvidenceBackedRollupSummary,
    LLMResult,
    RollupSummary,
    rollup_summary_from_evidence,
)
from src.validation.evidence_processor import (
    EvidenceProcessingResult,
    apply_rescue_reviews_to_rollup,
    process_rollup_evidence_strict,
    save_evidence_audit,
)
from src.validation.evidence_validator import (
    build_quarter_evidence_corpus,
    validate_rollup_evidence,
)
from src.validation.rescue_judge import RescueJudge
from src.validation.rescue_orchestrator import augment_rescue_reviews_with_retries

logger = logging.getLogger(__name__)


class RollupSummarizer:
    def __init__(
        self,
        client: AnthropicClient,
        skip_rescue_judge: bool = False,
    ):
        self.client = client
        self.system_prompt = load_prompt("rollup.txt")
        self.skip_rescue_judge = skip_rescue_judge
        self.rescue_judge = RescueJudge(client)

    def summarize(
        self,
        company_name: str,
        quarter_outputs: list[ValidatedQuarterOutput],
    ) -> tuple[RollupSummary, LLMResult]:
        label = f"{company_name}_rollup"
        quarter_evidence = [output.evidence for output in quarter_outputs]
        payload = [evidence.model_dump() for evidence in quarter_evidence]
        user_content = (
            f"Company: {company_name}\n\n"
            f"Validated quarter summaries with evidence (JSON):\n"
            f"{json.dumps(payload, indent=2)}"
        )

        evidence, result = self.client.complete_json(
            system_prompt=self.system_prompt,
            user_content=user_content,
            response_model=EvidenceBackedRollupSummary,
            label=label,
        )
        evidence.company_name = company_name
        evidence.quarter = "All (8Q rollup)"

        source = build_quarter_evidence_corpus(quarter_evidence)

        if self.skip_rescue_judge:
            processed = process_rollup_evidence_strict(evidence, quarter_evidence)
        else:
            validation = validate_rollup_evidence(evidence, quarter_evidence)
            if validation.is_valid:
                total = (
                    len(evidence.what_happened)
                    + len(evidence.positives)
                    + len(evidence.negatives)
                    + 1
                )
                processed = EvidenceProcessingResult(
                    evidence=evidence,
                    verbatim_kept=total,
                )
            else:
                rescue_result, _ = self.rescue_judge.review_validation_result(
                    validation,
                    source,
                    label,
                )
                rescue_result = augment_rescue_reviews_with_retries(
                    self.rescue_judge,
                    validation.failures,
                    rescue_result,
                    source,
                    label,
                )
                processed = apply_rescue_reviews_to_rollup(
                    evidence,
                    validation,
                    rescue_result,
                    source,
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
        assert isinstance(final_evidence, EvidenceBackedRollupSummary)
        summary = rollup_summary_from_evidence(final_evidence)
        return summary, result
