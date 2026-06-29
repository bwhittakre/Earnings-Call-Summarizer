from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from src.ingest.call_date import resolve_call_date
from src.ingest.loader import LoadedTranscripts, load_transcripts, transcript_audit_label
from src.ingest.reported_quarter import resolve_reported_quarter
from src.llm.anthropic_client import AnthropicClient
from src.llm.quarter_summarizer import QuarterSummarizer, ValidatedQuarterOutput
from src.market.constants import PRIOR_QUARTER_PRICE_COUNT
from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH
from src.market.pipeline import MarketContext, build_market_context, resolve_call_date_value
from src.schemas.models import QuarterSummary

logger = logging.getLogger(__name__)


def run_pipeline(
    client: AnthropicClient,
    transcript_path: str,
    expected_quarters: int = 1,
    quarter: str | None = None,
    skip_rescue_judge: bool = False,
    ticker: str | None = None,
    fiscal_calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    quarter_end_date_overrides: dict[str, date] | None = None,
    reported_quarter_override: str | None = None,
    price_fetcher=None,
    price_history_quarters: int | None = None,
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
        ticker=ticker,
        fiscal_calendars_path=fiscal_calendars_path,
        quarter_end_date_overrides=quarter_end_date_overrides,
        reported_quarter_override=reported_quarter_override,
        price_fetcher=price_fetcher,
        price_history_quarters=price_history_quarters,
    )


def run_pipeline_from_loaded(
    client: AnthropicClient,
    loaded: LoadedTranscripts,
    skip_rescue_judge: bool = False,
    ticker: str | None = None,
    fiscal_calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    quarter_end_date_overrides: dict[str, date] | None = None,
    reported_quarter_override: str | None = None,
    price_fetcher=None,
    price_history_quarters: int | None = None,
) -> list[QuarterSummary]:
    quarter_summarizer = QuarterSummarizer(
        client,
        skip_rescue_judge=skip_rescue_judge,
    )
    history_quarters = (
        price_history_quarters
        if price_history_quarters is not None
        else PRIOR_QUARTER_PRICE_COUNT
    )

    quarter_outputs: list[ValidatedQuarterOutput] = []
    for item in sorted(loaded.files, key=lambda file: file.quarter):
        quarter = item.quarter
        label = transcript_audit_label(item)
        transcript_text = loaded.transcripts[quarter]
        market_context: MarketContext | None = None
        if ticker:
            call_date = resolve_call_date_value(transcript_text)
            reported_quarter = resolve_reported_quarter(
                transcript_text,
                cli_override=reported_quarter_override,
            )
            market_context = build_market_context(
                ticker=ticker,
                transcript_text=transcript_text,
                call_date=call_date,
                reported_quarter=reported_quarter,
                transcript_file=item,
                calendars_path=fiscal_calendars_path,
                date_overrides=quarter_end_date_overrides,
                fetcher=price_fetcher,
                price_history_quarters=history_quarters,
            )
            logger.info(
                "Fetched %s prior-quarter prices for %s "
                "(reported=%s, call_date=%s)",
                len(market_context.prices),
                market_context.ticker,
                market_context.reported_quarter,
                market_context.call_date.isoformat(),
            )

        logger.info(
            "Summarizing %s (%s chars)",
            quarter,
            len(transcript_text),
        )
        output, result = quarter_summarizer.summarize(
            quarter=quarter,
            transcript_text=transcript_text,
            label=label,
            price_block_text=(
                market_context.price_block_text if market_context else None
            ),
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

    summaries: list[QuarterSummary] = []
    for item, output in zip(
        sorted(loaded.files, key=lambda file: file.quarter),
        quarter_outputs,
    ):
        call_date = resolve_call_date(
            loaded.transcripts[item.quarter],
            output.summary.call_date,
        )
        summaries.append(
            output.summary.model_copy(update={"call_date": call_date})
        )
    return summaries
