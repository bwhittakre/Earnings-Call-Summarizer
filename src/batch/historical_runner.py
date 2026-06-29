from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from src.batch.models import BatchQuarterResult, DeferredQuarter
from src.ingest.documents.cache import ticker_documents_folder
from src.ingest.documents.loader import load_quarter_documents
from src.ingest.documents.models import DocumentFetchError, DocumentLoadError, FetchRequest
from src.ingest.documents.orchestrator import fetch_quarter_documents
from src.llm.anthropic_client import AnthropicClient
from src.market.constants import BATCH_PRIOR_QUARTER_PRICE_COUNT
from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH
from src.market.quarter_labels import batch_quarter_labels_for_ticker, quarter_sort_key
from src.pipeline.runner import run_document_pipeline_from_loaded

logger = logging.getLogger(__name__)


def _failed_result(
    quarter_label: str,
    error_message: str,
    *,
    knowledge_cutoff: date | None = None,
    manifest_path: Path | None = None,
    attempts: int = 1,
) -> BatchQuarterResult:
    return BatchQuarterResult(
        quarter_label=quarter_label,
        status="failed",
        summary=None,
        error_message=error_message,
        knowledge_cutoff=knowledge_cutoff,
        manifest_path=manifest_path,
        attempts=attempts,
        last_error=error_message,
    )


def _skipped_result(
    deferred: DeferredQuarter,
    error_message: str,
) -> BatchQuarterResult:
    return BatchQuarterResult(
        quarter_label=deferred.quarter_label,
        status="skipped",
        summary=None,
        error_message=error_message,
        knowledge_cutoff=deferred.knowledge_cutoff,
        manifest_path=deferred.manifest_path,
        attempts=2,
        last_error=error_message,
    )


def _load_or_fetch_bundle(
    *,
    quarter_label: str,
    ticker_key: str,
    folder: Path,
    fetch: bool,
    force_fetch: bool,
    fiscal_calendars_path: Path,
    quarter_end_date_overrides: dict[str, date] | None,
):
    request = FetchRequest(
        ticker=ticker_key,
        quarter_label=quarter_label,
        trim_corpus=True,
    )
    if fetch or force_fetch:
        return fetch_quarter_documents(
            request,
            force=force_fetch,
            ticker_folder=folder,
            calendars_path=fiscal_calendars_path,
            date_overrides=quarter_end_date_overrides,
        )
    loaded = load_quarter_documents(
        folder,
        ticker=ticker_key,
        quarter=quarter_label,
        ticker_folder=folder,
    )
    return loaded.bundle


def _run_quarter_pipeline(
    client: AnthropicClient,
    *,
    quarter_label: str,
    ticker_key: str,
    folder: Path,
    skip_rescue_judge: bool,
    use_batch_prompt: bool = True,
    fiscal_calendars_path: Path,
    quarter_end_date_overrides: dict[str, date] | None,
    price_history_quarters: int,
):
    loaded = load_quarter_documents(
        folder,
        ticker=ticker_key,
        quarter=quarter_label,
        ticker_folder=folder,
    )
    output = run_document_pipeline_from_loaded(
        client,
        loaded,
        ticker=ticker_key,
        skip_rescue_judge=skip_rescue_judge,
        use_batch_prompt=use_batch_prompt,
        fiscal_calendars_path=fiscal_calendars_path,
        quarter_end_date_overrides=quarter_end_date_overrides,
        reported_quarter_override=quarter_label,
        price_history_quarters=price_history_quarters,
    )
    return output


def run_historical_batch(
    client: AnthropicClient | None,
    *,
    ticker: str,
    years: int = 10,
    end_quarter: str | None = None,
    quarter_count: int | None = None,
    price_history_quarters: int = BATCH_PRIOR_QUARTER_PRICE_COUNT,
    skip_rescue_judge: bool = True,
    fetch: bool = False,
    force_fetch: bool = False,
    dry_run: bool = False,
    fiscal_calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    quarter_end_date_overrides: dict[str, date] | None = None,
    ticker_folder: Path | None = None,
) -> list[BatchQuarterResult]:
    ticker_key = ticker.strip().upper()
    folder = ticker_folder or ticker_documents_folder(ticker_key)
    count = quarter_count if quarter_count is not None else years * 4
    quarter_labels = batch_quarter_labels_for_ticker(
        ticker_key,
        count,
        end_label=end_quarter,
        calendars_path=fiscal_calendars_path,
    )

    results_by_label: dict[str, BatchQuarterResult] = {}
    deferred: list[DeferredQuarter] = []

    for index, quarter_label in enumerate(quarter_labels, start=1):
        logger.info(
            "Batch pass 1 — %s/%s: %s %s",
            index,
            len(quarter_labels),
            ticker_key,
            quarter_label,
        )
        sort_key = quarter_sort_key(quarter_label)
        try:
            bundle = _load_or_fetch_bundle(
                quarter_label=quarter_label,
                ticker_key=ticker_key,
                folder=folder,
                fetch=fetch,
                force_fetch=force_fetch,
                fiscal_calendars_path=fiscal_calendars_path,
                quarter_end_date_overrides=quarter_end_date_overrides,
            )
        except (DocumentFetchError, DocumentLoadError) as exc:
            results_by_label[quarter_label] = _failed_result(quarter_label, str(exc))
            continue
        except Exception as exc:
            results_by_label[quarter_label] = _failed_result(quarter_label, str(exc))
            continue

        manifest_path = bundle.cache_dir / "manifest.json"
        if dry_run or client is None:
            results_by_label[quarter_label] = BatchQuarterResult(
                quarter_label=quarter_label,
                status="success",
                summary=None,
                knowledge_cutoff=bundle.knowledge_cutoff,
                manifest_path=manifest_path,
                attempts=1,
            )
            continue

        try:
            output = _run_quarter_pipeline(
                client,
                quarter_label=quarter_label,
                ticker_key=ticker_key,
                folder=folder,
                skip_rescue_judge=skip_rescue_judge,
                fiscal_calendars_path=fiscal_calendars_path,
                quarter_end_date_overrides=quarter_end_date_overrides,
                price_history_quarters=price_history_quarters,
            )
            results_by_label[quarter_label] = BatchQuarterResult(
                quarter_label=quarter_label,
                status="success",
                summary=output.summary,
                knowledge_cutoff=bundle.knowledge_cutoff,
                manifest_path=manifest_path,
                attempts=1,
                backfilled_from_analysis=list(output.backfilled_from_analysis or []),
            )
        except Exception as exc:
            logger.warning(
                "Deferring %s %s after pipeline error: %s",
                ticker_key,
                quarter_label,
                exc,
            )
            deferred.append(
                DeferredQuarter(
                    quarter_label=quarter_label,
                    knowledge_cutoff=bundle.knowledge_cutoff,
                    manifest_path=manifest_path,
                    last_error=str(exc),
                    sort_key=sort_key,
                )
            )

    if deferred and client is not None and not dry_run:
        deferred.sort(key=lambda item: item.sort_key)
        logger.info("Batch pass 2 — retrying %s deferred quarter(s)", len(deferred))
        for index, item in enumerate(deferred, start=1):
            logger.info(
                "Batch pass 2 — %s/%s: %s %s",
                index,
                len(deferred),
                ticker_key,
                item.quarter_label,
            )
            try:
                output = _run_quarter_pipeline(
                    client,
                    quarter_label=item.quarter_label,
                    ticker_key=ticker_key,
                    folder=folder,
                    skip_rescue_judge=skip_rescue_judge,
                    fiscal_calendars_path=fiscal_calendars_path,
                    quarter_end_date_overrides=quarter_end_date_overrides,
                    price_history_quarters=price_history_quarters,
                )
                results_by_label[item.quarter_label] = BatchQuarterResult(
                    quarter_label=item.quarter_label,
                    status="success",
                    summary=output.summary,
                    knowledge_cutoff=item.knowledge_cutoff,
                    manifest_path=item.manifest_path,
                    attempts=2,
                    backfilled_from_analysis=list(output.backfilled_from_analysis or []),
                )
            except Exception as exc:
                logger.error(
                    "Skipping %s %s after second pipeline failure: %s",
                    ticker_key,
                    item.quarter_label,
                    exc,
                )
                results_by_label[item.quarter_label] = _skipped_result(
                    item,
                    str(exc),
                )

    return [
        results_by_label[label]
        for label in quarter_labels
        if label in results_by_label
    ]
