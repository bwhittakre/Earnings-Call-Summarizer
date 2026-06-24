from __future__ import annotations

import logging
from pathlib import Path

from src.ingest.loader import LoadedTranscripts, load_company_transcripts
from src.llm.anthropic_client import AnthropicClient
from src.llm.quarter_summarizer import QuarterSummarizer, ValidatedQuarterOutput
from src.llm.rollup_summarizer import RollupSummarizer
from src.schemas.models import QuarterSummary, RollupSummary

logger = logging.getLogger(__name__)


def run_company_pipeline(
    client: AnthropicClient,
    company_name: str,
    transcript_folder: str,
    expected_quarters: int = 8,
    skip_rollup: bool = False,
    skip_rescue_judge: bool = False,
) -> list[QuarterSummary | RollupSummary]:
    loaded = load_company_transcripts(
        company_name=company_name,
        folder=Path(transcript_folder),
        expected_quarters=expected_quarters,
    )
    return run_company_pipeline_from_loaded(
        client,
        loaded,
        skip_rollup=skip_rollup,
        skip_rescue_judge=skip_rescue_judge,
    )


def run_company_pipeline_from_loaded(
    client: AnthropicClient,
    loaded: LoadedTranscripts,
    skip_rollup: bool = False,
    skip_rescue_judge: bool = False,
) -> list[QuarterSummary | RollupSummary]:
    quarter_summarizer = QuarterSummarizer(
        client,
        skip_rescue_judge=skip_rescue_judge,
    )
    rollup_summarizer = RollupSummarizer(
        client,
        skip_rescue_judge=skip_rescue_judge,
    )

    quarter_outputs: list[ValidatedQuarterOutput] = []
    for quarter in sorted(loaded.transcripts.keys()):
        logger.info(
            "Summarizing %s %s (%s chars)",
            loaded.company_name,
            quarter,
            len(loaded.transcripts[quarter]),
        )
        output, result = quarter_summarizer.summarize(
            company_name=loaded.company_name,
            quarter=quarter,
            transcript_text=loaded.transcripts[quarter],
        )
        logger.info(
            "  tokens: in=%s out=%s confidence=%s (evidence validated)",
            result.usage.input_tokens,
            result.usage.output_tokens,
            output.summary.confidence,
        )
        quarter_outputs.append(output)

    results: list[QuarterSummary | RollupSummary] = [
        output.summary for output in quarter_outputs
    ]

    if not skip_rollup:
        logger.info("Creating rollup for %s", loaded.company_name)
        rollup, rollup_result = rollup_summarizer.summarize(
            company_name=loaded.company_name,
            quarter_outputs=quarter_outputs,
        )
        logger.info(
            "  rollup tokens: in=%s out=%s confidence=%s (evidence validated)",
            rollup_result.usage.input_tokens,
            rollup_result.usage.output_tokens,
            rollup.confidence,
        )
        results.append(rollup)

    return results
