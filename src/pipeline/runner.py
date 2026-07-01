from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from src.export.csv_writer import sort_quarter_summaries
from src.ingest.dates import resolve_as_of_date_text
from src.ingest.filings import FilingPackage, load_filing_packages
from src.ingest.filings.fiscal import parse_quarters_list
from src.ingest.filings.corpus import DEFAULT_MAX_CORPUS_CHARS, truncate_corpus_for_llm
from src.ingest.filings.loader import ExcerptConfig
from src.ingest.filings.manifest import resolve_quarter_end_overrides
from src.llm.anthropic_client import AnthropicClient
from src.llm.quarter_summarizer import QuarterSummarizer, ValidatedQuarterOutput
from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH
from src.market.pipeline import MarketContext, build_market_context
from src.pipeline.point_in_time import PointInTimeConfig
from src.schemas.models import QuarterSummary

logger = logging.getLogger(__name__)


def run_pipeline(
    client: AnthropicClient,
    filings_root: Path,
    *,
    companies: str,
    quarter: str,
    skip_rescue_judge: bool = False,
    ticker: str | None = None,
    fiscal_calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    quarter_end_date_overrides: dict[str, date] | None = None,
    price_fetcher=None,
    point_in_time: PointInTimeConfig | None = None,
    max_corpus_chars: int = DEFAULT_MAX_CORPUS_CHARS,
    excerpt_config: ExcerptConfig | None = None,
) -> list[QuarterSummary]:
    pit = point_in_time or PointInTimeConfig.disabled()
    quarters = parse_quarters_list(quarter)
    summaries: list[QuarterSummary] = []
    for normalized_quarter in quarters:
        if len(quarters) > 1:
            logger.info("Processing quarter %s", normalized_quarter)
        packages = load_filing_packages(
            filings_root,
            companies=companies,
            quarter=normalized_quarter,
            require_as_of_date=pit.active,
            excerpt_config=excerpt_config,
        )
        summaries.extend(
            run_pipeline_from_packages(
                client,
                packages,
                skip_rescue_judge=skip_rescue_judge,
                ticker=ticker,
                fiscal_calendars_path=fiscal_calendars_path,
                quarter_end_date_overrides=quarter_end_date_overrides,
                price_fetcher=price_fetcher,
                point_in_time=pit,
                max_corpus_chars=max_corpus_chars,
            )
        )
    return sort_quarter_summaries(summaries)


def run_pipeline_from_packages(
    client: AnthropicClient,
    packages: list[FilingPackage],
    skip_rescue_judge: bool = False,
    ticker: str | None = None,
    fiscal_calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    quarter_end_date_overrides: dict[str, date] | None = None,
    price_fetcher=None,
    point_in_time: PointInTimeConfig | None = None,
    max_corpus_chars: int = DEFAULT_MAX_CORPUS_CHARS,
) -> list[QuarterSummary]:
    pit = point_in_time or PointInTimeConfig.disabled()
    if pit.active:
        skip_rescue_judge = True
        if not pit.include_prices:
            if ticker:
                logger.warning(
                    "Ignoring --ticker in point-in-time mode (documents-only)."
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
    for package in packages:
        label = package.audit_label()
        as_of_date = package.as_of_date
        if pit.active and as_of_date is None:
            raise ValueError(
                f"Point-in-time mode requires as_of_date in manifest for {label}."
            )

        market_context: MarketContext | None = None
        effective_ticker = ticker or package.ticker
        if ticker and as_of_date is not None:
            manifest_overrides = resolve_quarter_end_overrides(
                package.folder,
                quarter=package.quarter,
                as_of_date=as_of_date,
            )
            merged_overrides = {**(quarter_end_date_overrides or {}), **manifest_overrides}
            market_context = build_market_context(
                ticker=effective_ticker,
                as_of_date=as_of_date,
                reported_quarter=package.quarter,
                audit_label=label,
                calendars_path=fiscal_calendars_path,
                date_overrides=merged_overrides,
                fetcher=price_fetcher,
                point_in_time=pit,
            )
            logger.info(
                "Fetched %s prior-quarter prices for %s "
                "(reported=%s, as_of_date=%s)",
                len(market_context.prices),
                market_context.ticker,
                market_context.reported_quarter,
                market_context.as_of_date.isoformat(),
            )

        if pit.active:
            logger.info(
                "Point-in-time mode: as_of_date=%s reported=%s prices=%s rescue=off",
                as_of_date.isoformat() if as_of_date else None,
                package.quarter,
                bool(market_context),
            )

        corpus_text, trunc_warnings = truncate_corpus_for_llm(
            package.analysis_corpus_text,
            max_corpus_chars,
        )
        for warning in trunc_warnings:
            logger.warning("%s: %s", label, warning)

        logger.info(
            "Summarizing %s (%s analysis chars, raw %s%s)",
            label,
            len(corpus_text),
            len(package.raw_corpus_text),
            f", truncated from {len(package.analysis_corpus_text):,}" if trunc_warnings else "",
        )
        output, result = quarter_summarizer.summarize(
            quarter=package.quarter,
            corpus_text=corpus_text,
            label=label,
            price_block_text=(
                market_context.price_block_text if market_context else None
            ),
            as_of_date=as_of_date,
            company_name=package.company_name,
            is_q4=package.is_q4,
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
    for package, output in zip(packages, quarter_outputs):
        as_of_date_text = resolve_as_of_date_text(
            package.as_of_date_text,
            output.summary.as_of_date,
        )
        summaries.append(
            output.summary.model_copy(update={"as_of_date": as_of_date_text})
        )
    return summaries
