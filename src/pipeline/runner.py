from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from src.ingest.call_date import format_call_date, resolve_call_date
from src.ingest.loader import LoadedTranscripts, load_transcripts, transcript_audit_label
from src.llm.anthropic_client import AnthropicClient
from src.llm.quarter_summarizer import QuarterSummarizer, ValidatedQuarterOutput
from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH
from src.market.pipeline import MarketContext, build_market_context
from src.pipeline.point_in_time import PointInTimeConfig
from src.pipeline.strict_anchoring import resolve_strict_anchoring
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
    point_in_time: PointInTimeConfig | None = None,
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
        point_in_time=point_in_time,
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
    point_in_time: PointInTimeConfig | None = None,
) -> list[QuarterSummary]:
    pit = point_in_time or PointInTimeConfig.disabled()
    if pit.active:
        skip_rescue_judge = True
        if not pit.include_prices:
            if ticker:
                logger.warning(
                    "Ignoring --ticker in point-in-time mode (transcript-only)."
                )
            ticker = None
        elif not ticker:
            raise ValueError(
                "Point-in-time-with-prices mode requires --ticker."
            )

    quarter_summarizer = QuarterSummarizer(
        client,
        skip_rescue_judge=skip_rescue_judge,
        point_in_time=pit,
    )

    quarter_outputs: list[ValidatedQuarterOutput] = []
    for item in sorted(loaded.files, key=lambda file: file.quarter):
        quarter = item.quarter
        label = transcript_audit_label(item)
        transcript_text = loaded.transcripts[quarter]
        call_date: date | None = None
        reported_quarter: str | None = None
        if pit.active or ticker:
            call_date, reported_quarter = resolve_strict_anchoring(
                transcript_text=transcript_text,
                filename_quarter=item.quarter,
                point_in_time=pit,
                reported_quarter_override=reported_quarter_override,
                require_call_date=bool(ticker),
            )
        market_context: MarketContext | None = None
        if ticker and reported_quarter is not None and call_date is not None:
            market_context = build_market_context(
                ticker=ticker,
                transcript_text=transcript_text,
                call_date=call_date,
                reported_quarter=reported_quarter,
                transcript_file=item,
                calendars_path=fiscal_calendars_path,
                date_overrides=quarter_end_date_overrides,
                fetcher=price_fetcher,
                point_in_time=pit,
            )
            logger.info(
                "Fetched %s prior-quarter prices for %s "
                "(reported=%s, call_date=%s)",
                len(market_context.prices),
                market_context.ticker,
                market_context.reported_quarter,
                market_context.call_date.isoformat(),
            )

        if pit.active:
            logger.info(
                "Point-in-time mode: call_date=%s reported=%s prices=%s rescue=off",
                call_date.isoformat(),
                reported_quarter,
                bool(market_context),
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
            call_date=call_date,
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
        call_date_text = resolve_call_date(
            loaded.transcripts[item.quarter],
            output.summary.call_date,
        )
        summaries.append(
            output.summary.model_copy(update={"call_date": call_date_text})
        )
    return summaries
