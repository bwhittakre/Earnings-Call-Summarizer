from __future__ import annotations

import logging
from pathlib import Path

from src.ingest.loader import LoadedTranscripts, load_transcripts, transcript_audit_label
from src.llm.anthropic_client import AnthropicClient
from src.llm.quarter_summarizer import QuarterSummarizer, ValidatedQuarterOutput
from src.schemas.models import QuarterSummary

logger = logging.getLogger(__name__)


def run_pipeline(
    client: AnthropicClient,
    transcript_path: str,
    expected_quarters: int = 1,
    quarter: str | None = None,
    skip_rescue_judge: bool = False,
) -> list[QuarterSummary]:
    loaded = load_transcripts(
        transcript_path=Path(transcript_path),
        expected_quarters=expected_quarters,
        quarter=quarter,
    )
    return run_pipeline_from_loaded(
        client,
        loaded,
        skip_rescue_judge=skip_rescue_judge,
    )


def run_pipeline_from_loaded(
    client: AnthropicClient,
    loaded: LoadedTranscripts,
    skip_rescue_judge: bool = False,
) -> list[QuarterSummary]:
    quarter_summarizer = QuarterSummarizer(
        client,
        skip_rescue_judge=skip_rescue_judge,
    )

    quarter_outputs: list[ValidatedQuarterOutput] = []
    for item in sorted(loaded.files, key=lambda file: file.quarter):
        quarter = item.quarter
        label = transcript_audit_label(item)
        logger.info(
            "Summarizing %s (%s chars)",
            quarter,
            len(loaded.transcripts[quarter]),
        )
        output, result = quarter_summarizer.summarize(
            quarter=quarter,
            transcript_text=loaded.transcripts[quarter],
            label=label,
        )
        logger.info(
            "Detected company: %s",
            output.summary.company_name,
        )
        logger.info(
            "  tokens: in=%s out=%s confidence_score=%s (evidence validated)",
            result.usage.input_tokens,
            result.usage.output_tokens,
            output.summary.confidence_score,
        )
        quarter_outputs.append(output)

    return [output.summary for output in quarter_outputs]
