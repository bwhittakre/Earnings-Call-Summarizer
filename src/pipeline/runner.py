from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from src.ingest.call_date import resolve_call_date
from src.ingest.documents.loader import LoadedQuarterDocuments, load_quarter_documents
from src.ingest.loader import LoadedTranscripts, load_transcripts, transcript_audit_label
from src.ingest.reported_quarter import resolve_reported_quarter
from src.llm.anthropic_client import AnthropicClient
from src.llm.quarter_summarizer import QuarterSummarizer, ValidatedQuarterOutput
from src.market.constants import PRIOR_QUARTER_PRICE_COUNT
from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH
from src.market.pipeline import MarketContext, build_market_context, resolve_call_date_value, resolve_event_date_from_bundle
from src.schemas.models import QuarterSummary

logger = logging.getLogger(__name__)


def _summarize_loaded_source(
    client: AnthropicClient,
    *,
    quarter: str,
    source_text: str,
    label: str,
    skip_rescue_judge: bool,
    use_batch_prompt: bool = False,
    ticker: str | None,
    fiscal_calendars_path: Path,
    quarter_end_date_overrides: dict[str, date] | None,
    reported_quarter_override: str | None,
    price_fetcher,
    price_history_quarters: int,
    transcript_file=None,
    document_bundle=None,
) -> ValidatedQuarterOutput:
    quarter_summarizer = QuarterSummarizer(
        client,
        skip_rescue_judge=skip_rescue_judge,
        use_batch_prompt=use_batch_prompt,
    )
    market_context: MarketContext | None = None
    if ticker:
        if document_bundle is not None:
            call_date = resolve_event_date_from_bundle(source_text, document_bundle)
        else:
            call_date = resolve_call_date_value(source_text)
        reported_quarter = resolve_reported_quarter(
            source_text,
            cli_override=reported_quarter_override or (
                quarter if document_bundle is not None else None
            ),
        )
        audit_file = transcript_file
        if audit_file is None and document_bundle is not None:
            from src.ingest.loader import TranscriptFile

            audit_file = TranscriptFile(
                path=document_bundle.cache_dir / "manifest.json",
                quarter=quarter,
                quarter_from_filename=True,
            )
        market_context = build_market_context(
            ticker=ticker,
            transcript_text=source_text,
            call_date=call_date,
            reported_quarter=reported_quarter,
            transcript_file=audit_file,
            calendars_path=fiscal_calendars_path,
            date_overrides=quarter_end_date_overrides,
            fetcher=price_fetcher,
            price_history_quarters=price_history_quarters,
        )
        logger.info(
            "Fetched %s prior-quarter prices for %s (reported=%s, call_date=%s)",
            len(market_context.prices),
            market_context.ticker,
            market_context.reported_quarter,
            market_context.call_date.isoformat(),
        )

    logger.info("Summarizing %s (%s chars)", quarter, len(source_text))
    output, result = quarter_summarizer.summarize(
        quarter=quarter,
        source_text=source_text,
        label=label,
        price_block_text=market_context.price_block_text if market_context else None,
    )
    logger.info("Detected company: %s", output.summary.company_name)
    logger.info(
        "  tokens: in=%s out=%s confidence_score=%s (evidence validated)",
        result.usage.input_tokens,
        result.usage.output_tokens,
        output.summary.confidence_score,
    )
    return output


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


def run_document_pipeline(
    client: AnthropicClient,
    documents_path: Path,
    *,
    ticker: str,
    quarter: str,
    skip_rescue_judge: bool = False,
    fiscal_calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    quarter_end_date_overrides: dict[str, date] | None = None,
    reported_quarter_override: str | None = None,
    price_fetcher=None,
    price_history_quarters: int | None = None,
) -> list[QuarterSummary]:
    from src.ingest.documents.loader import resolve_ticker_folder

    ticker_folder = resolve_ticker_folder(documents_path, ticker)
    loaded_docs = load_quarter_documents(
        documents_path,
        ticker=ticker,
        quarter=quarter,
        ticker_folder=ticker_folder,
    )
    output = run_document_pipeline_from_loaded(
        client,
        loaded_docs,
        ticker=ticker,
        skip_rescue_judge=skip_rescue_judge,
        fiscal_calendars_path=fiscal_calendars_path,
        quarter_end_date_overrides=quarter_end_date_overrides,
        reported_quarter_override=reported_quarter_override,
        price_fetcher=price_fetcher,
        price_history_quarters=price_history_quarters,
    )
    return [output.summary]


def run_document_pipeline_from_loaded(
    client: AnthropicClient,
    loaded: LoadedQuarterDocuments,
    *,
    ticker: str,
    skip_rescue_judge: bool = False,
    use_batch_prompt: bool = False,
    fiscal_calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    quarter_end_date_overrides: dict[str, date] | None = None,
    reported_quarter_override: str | None = None,
    price_fetcher=None,
    price_history_quarters: int | None = None,
) -> ValidatedQuarterOutput:
    history_quarters = (
        price_history_quarters
        if price_history_quarters is not None
        else PRIOR_QUARTER_PRICE_COUNT
    )
    output = _summarize_loaded_source(
        client,
        quarter=loaded.quarter_label,
        source_text=loaded.corpus_text,
        label=loaded.audit_label,
        skip_rescue_judge=skip_rescue_judge,
        use_batch_prompt=use_batch_prompt,
        ticker=ticker,
        fiscal_calendars_path=fiscal_calendars_path,
        quarter_end_date_overrides=quarter_end_date_overrides,
        reported_quarter_override=reported_quarter_override,
        price_fetcher=price_fetcher,
        price_history_quarters=history_quarters,
        document_bundle=loaded.bundle,
    )
    call_date = resolve_call_date(loaded.corpus_text, output.summary.call_date)
    return ValidatedQuarterOutput(
        summary=output.summary.model_copy(update={"call_date": call_date}),
        evidence=output.evidence,
        backfilled_from_analysis=output.backfilled_from_analysis,
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
        output = _summarize_loaded_source(
            client,
            quarter=quarter,
            source_text=transcript_text,
            label=label,
            skip_rescue_judge=skip_rescue_judge,
            ticker=ticker,
            fiscal_calendars_path=fiscal_calendars_path,
            quarter_end_date_overrides=quarter_end_date_overrides,
            reported_quarter_override=reported_quarter_override,
            price_fetcher=price_fetcher,
            price_history_quarters=history_quarters,
            transcript_file=item,
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
