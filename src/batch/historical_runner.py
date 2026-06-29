from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.batch.models import BatchQuarterResult, DeferredQuarter
from src.ingest.documents.cache import ticker_documents_folder
from src.ingest.documents.config import resolve_ticker_config
from src.ingest.documents.fetch.edgar_client import EdgarClient, normalize_cik
from src.ingest.documents.fetch.filings_cache import get_ticker_filings
from src.ingest.documents.fetch_manifest import build_fetch_summary
from src.ingest.documents.loader import LoadedQuarterDocuments, bundle_to_loaded, load_quarter_documents
from src.ingest.documents.models import DocumentFetchError, DocumentLoadError, FetchRequest, QuarterDocumentBundle
from src.ingest.documents.orchestrator import fetch_quarter_documents
from src.llm.anthropic_client import AnthropicClient
from src.market.constants import BATCH_PRIOR_QUARTER_PRICE_COUNT
from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH
from src.market.history_cache import batch_history_fetcher, clear_history_cache
from src.market.quarter_labels import batch_quarter_labels_for_ticker, quarter_sort_key
from src.market.stock_prices import HistoryFetcher
from src.pipeline.runner import run_document_pipeline_from_loaded

logger = logging.getLogger(__name__)

DEFAULT_BATCH_WORKERS = 4
DEFAULT_FETCH_WORKERS = 1


@dataclass(frozen=True)
class _FetchOutcome:
    quarter_label: str
    loaded: LoadedQuarterDocuments | None = None
    error: str | None = None


@dataclass(frozen=True)
class _ScoreOutcome:
    quarter_label: str
    result: BatchQuarterResult | None = None
    deferred: DeferredQuarter | None = None


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
    trim_corpus: bool,
    edgar_client: EdgarClient | None = None,
) -> QuarterDocumentBundle:
    request = FetchRequest(
        ticker=ticker_key,
        quarter_label=quarter_label,
        trim_corpus=trim_corpus,
    )
    if fetch or force_fetch:
        return fetch_quarter_documents(
            request,
            force=force_fetch,
            ticker_folder=folder,
            calendars_path=fiscal_calendars_path,
            date_overrides=quarter_end_date_overrides,
            client=edgar_client,
        )
    loaded = load_quarter_documents(
        folder,
        ticker=ticker_key,
        quarter=quarter_label,
        ticker_folder=folder,
    )
    return loaded.bundle


def _fetch_one_quarter(
    *,
    quarter_label: str,
    ticker_key: str,
    folder: Path,
    fetch: bool,
    force_fetch: bool,
    fiscal_calendars_path: Path,
    quarter_end_date_overrides: dict[str, date] | None,
    trim_corpus: bool,
    edgar_client: EdgarClient | None,
) -> _FetchOutcome:
    try:
        bundle = _load_or_fetch_bundle(
            quarter_label=quarter_label,
            ticker_key=ticker_key,
            folder=folder,
            fetch=fetch,
            force_fetch=force_fetch,
            fiscal_calendars_path=fiscal_calendars_path,
            quarter_end_date_overrides=quarter_end_date_overrides,
            trim_corpus=trim_corpus,
            edgar_client=edgar_client,
        )
        loaded = bundle_to_loaded(bundle, ticker=ticker_key)
        return _FetchOutcome(quarter_label=quarter_label, loaded=loaded)
    except (DocumentFetchError, DocumentLoadError) as exc:
        return _FetchOutcome(quarter_label=quarter_label, error=str(exc))
    except Exception as exc:
        return _FetchOutcome(quarter_label=quarter_label, error=str(exc))


def _fetch_all_quarters(
    *,
    quarter_labels: list[str],
    ticker_key: str,
    folder: Path,
    fetch: bool,
    force_fetch: bool,
    fiscal_calendars_path: Path,
    quarter_end_date_overrides: dict[str, date] | None,
    trim_corpus: bool,
    edgar_client: EdgarClient | None,
    fetch_workers: int,
) -> tuple[dict[str, LoadedQuarterDocuments], dict[str, BatchQuarterResult]]:
    loaded_by_label: dict[str, LoadedQuarterDocuments] = {}
    failed_by_label: dict[str, BatchQuarterResult] = {}

    if fetch and edgar_client is not None:
        ticker_config = resolve_ticker_config(ticker_key)
        cik = normalize_cik(str(ticker_config["cik"]))
        get_ticker_filings(
            edgar_client,
            cik,
            folder,
            force_refresh=force_fetch,
        )

    worker_count = max(1, fetch_workers)
    logger.info(
        "Phase 1 fetch — %s quarters with %s worker(s)",
        len(quarter_labels),
        worker_count,
    )

    if worker_count == 1:
        for index, quarter_label in enumerate(quarter_labels, start=1):
            logger.info(
                "Phase 1 fetch — %s/%s: %s %s",
                index,
                len(quarter_labels),
                ticker_key,
                quarter_label,
            )
            outcome = _fetch_one_quarter(
                quarter_label=quarter_label,
                ticker_key=ticker_key,
                folder=folder,
                fetch=fetch,
                force_fetch=force_fetch,
                fiscal_calendars_path=fiscal_calendars_path,
                quarter_end_date_overrides=quarter_end_date_overrides,
                trim_corpus=trim_corpus,
                edgar_client=edgar_client,
            )
            if outcome.loaded is not None:
                loaded_by_label[outcome.quarter_label] = outcome.loaded
            elif outcome.error:
                failed_by_label[outcome.quarter_label] = _failed_result(
                    outcome.quarter_label,
                    outcome.error,
                )
    else:
        completed = 0
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = {
                pool.submit(
                    _fetch_one_quarter,
                    quarter_label=quarter_label,
                    ticker_key=ticker_key,
                    folder=folder,
                    fetch=fetch,
                    force_fetch=force_fetch,
                    fiscal_calendars_path=fiscal_calendars_path,
                    quarter_end_date_overrides=quarter_end_date_overrides,
                    trim_corpus=trim_corpus,
                    edgar_client=edgar_client,
                ): quarter_label
                for quarter_label in quarter_labels
            }
            for future in as_completed(futures):
                outcome = future.result()
                with lock:
                    completed += 1
                    if outcome.loaded is not None:
                        loaded_by_label[outcome.quarter_label] = outcome.loaded
                    elif outcome.error:
                        failed_by_label[outcome.quarter_label] = _failed_result(
                            outcome.quarter_label,
                            outcome.error,
                        )
                    logger.info(
                        "Phase 1 fetch — %s/%s complete (%s)",
                        completed,
                        len(quarter_labels),
                        outcome.quarter_label,
                    )

    logger.info(
        "Phase 1 fetch complete — loaded=%s failed=%s",
        len(loaded_by_label),
        len(failed_by_label),
    )
    return loaded_by_label, failed_by_label


def _run_quarter_pipeline(
    client: AnthropicClient,
    *,
    loaded: LoadedQuarterDocuments,
    ticker_key: str,
    skip_rescue_judge: bool,
    skip_analysis_repair: bool,
    fiscal_calendars_path: Path,
    quarter_end_date_overrides: dict[str, date] | None,
    price_history_quarters: int,
    price_fetcher: HistoryFetcher | None,
):
    return run_document_pipeline_from_loaded(
        client,
        loaded,
        ticker=ticker_key,
        skip_rescue_judge=skip_rescue_judge,
        skip_analysis_repair=skip_analysis_repair,
        use_batch_prompt=True,
        fiscal_calendars_path=fiscal_calendars_path,
        quarter_end_date_overrides=quarter_end_date_overrides,
        reported_quarter_override=loaded.quarter_label,
        price_history_quarters=price_history_quarters,
        price_fetcher=price_fetcher,
    )


def _score_one_quarter(
    *,
    client: AnthropicClient,
    loaded: LoadedQuarterDocuments,
    ticker_key: str,
    skip_rescue_judge: bool,
    skip_analysis_repair: bool,
    fiscal_calendars_path: Path,
    quarter_end_date_overrides: dict[str, date] | None,
    price_history_quarters: int,
    price_fetcher: HistoryFetcher | None,
    attempts: int = 1,
) -> _ScoreOutcome:
    quarter_label = loaded.quarter_label
    bundle = loaded.bundle
    manifest_path = bundle.cache_dir / "manifest.json"
    fetch_summary = build_fetch_summary(bundle, ticker=ticker_key)
    started = time.monotonic()
    try:
        output = _run_quarter_pipeline(
            client,
            loaded=loaded,
            ticker_key=ticker_key,
            skip_rescue_judge=skip_rescue_judge,
            skip_analysis_repair=skip_analysis_repair,
            fiscal_calendars_path=fiscal_calendars_path,
            quarter_end_date_overrides=quarter_end_date_overrides,
            price_history_quarters=price_history_quarters,
            price_fetcher=price_fetcher,
        )
        elapsed = time.monotonic() - started
        logger.info(
            "Scored %s %s in %.1fs (attempt %s)",
            ticker_key,
            quarter_label,
            elapsed,
            attempts,
        )
        return _ScoreOutcome(
            quarter_label=quarter_label,
            result=BatchQuarterResult(
                quarter_label=quarter_label,
                status="success",
                summary=output.summary,
                knowledge_cutoff=bundle.knowledge_cutoff,
                manifest_path=manifest_path,
                attempts=attempts,
                backfilled_from_analysis=list(output.backfilled_from_analysis or []),
                fetch_summary=fetch_summary,
                evidence_audit_path=output.evidence_audit_path,
                filing_evidence=output.evidence,
            ),
        )
    except Exception as exc:
        logger.warning(
            "Deferring %s %s after pipeline error: %s",
            ticker_key,
            quarter_label,
            exc,
        )
        return _ScoreOutcome(
            quarter_label=quarter_label,
            deferred=DeferredQuarter(
                quarter_label=quarter_label,
                knowledge_cutoff=bundle.knowledge_cutoff,
                manifest_path=manifest_path,
                last_error=str(exc),
                sort_key=quarter_sort_key(quarter_label),
            ),
        )


def _run_parallel_scoring(
    *,
    client: AnthropicClient,
    loaded_by_label: dict[str, LoadedQuarterDocuments],
    quarter_labels: list[str],
    ticker_key: str,
    skip_rescue_judge: bool,
    skip_analysis_repair: bool,
    fiscal_calendars_path: Path,
    quarter_end_date_overrides: dict[str, date] | None,
    price_history_quarters: int,
    price_fetcher: HistoryFetcher | None,
    batch_workers: int,
    attempts: int,
    phase_label: str,
) -> tuple[dict[str, BatchQuarterResult], list[DeferredQuarter]]:
    labels = [label for label in quarter_labels if label in loaded_by_label]
    results: dict[str, BatchQuarterResult] = {}
    deferred: list[DeferredQuarter] = []
    if not labels:
        return results, deferred

    worker_count = max(1, batch_workers)
    logger.info(
        "%s — scoring %s quarters with %s worker(s)",
        phase_label,
        len(labels),
        worker_count,
    )

    if worker_count == 1:
        for index, quarter_label in enumerate(labels, start=1):
            logger.info(
                "%s — %s/%s: %s %s",
                phase_label,
                index,
                len(labels),
                ticker_key,
                quarter_label,
            )
            outcome = _score_one_quarter(
                client=client,
                loaded=loaded_by_label[quarter_label],
                ticker_key=ticker_key,
                skip_rescue_judge=skip_rescue_judge,
                skip_analysis_repair=skip_analysis_repair,
                fiscal_calendars_path=fiscal_calendars_path,
                quarter_end_date_overrides=quarter_end_date_overrides,
                price_history_quarters=price_history_quarters,
                price_fetcher=price_fetcher,
                attempts=attempts,
            )
            if outcome.result is not None:
                results[outcome.quarter_label] = outcome.result
            elif outcome.deferred is not None:
                deferred.append(outcome.deferred)
        return results, deferred

    completed = 0
    lock = threading.Lock()
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = {
            pool.submit(
                _score_one_quarter,
                client=client,
                loaded=loaded_by_label[quarter_label],
                ticker_key=ticker_key,
                skip_rescue_judge=skip_rescue_judge,
                skip_analysis_repair=skip_analysis_repair,
                fiscal_calendars_path=fiscal_calendars_path,
                quarter_end_date_overrides=quarter_end_date_overrides,
                price_history_quarters=price_history_quarters,
                price_fetcher=price_fetcher,
                attempts=attempts,
            ): quarter_label
            for quarter_label in labels
        }
        for future in as_completed(futures):
            outcome = future.result()
            with lock:
                completed += 1
                if outcome.result is not None:
                    results[outcome.quarter_label] = outcome.result
                elif outcome.deferred is not None:
                    deferred.append(outcome.deferred)
                logger.info(
                    "%s — %s/%s complete (%s)",
                    phase_label,
                    completed,
                    len(labels),
                    outcome.quarter_label,
                )
    return results, deferred


def _retry_deferred_parallel(
    *,
    client: AnthropicClient,
    deferred: list[DeferredQuarter],
    loaded_by_label: dict[str, LoadedQuarterDocuments],
    ticker_key: str,
    folder: Path,
    trim_corpus: bool,
    fiscal_calendars_path: Path,
    quarter_end_date_overrides: dict[str, date] | None,
    edgar_client: EdgarClient | None,
    skip_rescue_judge: bool,
    skip_analysis_repair: bool,
    price_history_quarters: int,
    price_fetcher: HistoryFetcher | None,
    batch_workers: int,
) -> dict[str, BatchQuarterResult]:
    if not deferred:
        return {}

    deferred.sort(key=lambda item: item.sort_key)
    logger.info("Phase 3 retry — %s deferred quarter(s)", len(deferred))
    retry_loaded: dict[str, LoadedQuarterDocuments] = {}
    skipped: dict[str, BatchQuarterResult] = {}

    for item in deferred:
        loaded = loaded_by_label.get(item.quarter_label)
        if loaded is None:
            try:
                bundle = _load_or_fetch_bundle(
                    quarter_label=item.quarter_label,
                    ticker_key=ticker_key,
                    folder=folder,
                    fetch=False,
                    force_fetch=False,
                    fiscal_calendars_path=fiscal_calendars_path,
                    quarter_end_date_overrides=quarter_end_date_overrides,
                    trim_corpus=trim_corpus,
                    edgar_client=edgar_client,
                )
                loaded = bundle_to_loaded(bundle, ticker=ticker_key)
                loaded_by_label[item.quarter_label] = loaded
            except Exception as exc:
                skipped[item.quarter_label] = _skipped_result(item, str(exc))
                continue
        retry_loaded[item.quarter_label] = loaded

    retry_results, still_deferred = _run_parallel_scoring(
        client=client,
        loaded_by_label=retry_loaded,
        quarter_labels=list(retry_loaded.keys()),
        ticker_key=ticker_key,
        skip_rescue_judge=skip_rescue_judge,
        skip_analysis_repair=skip_analysis_repair,
        fiscal_calendars_path=fiscal_calendars_path,
        quarter_end_date_overrides=quarter_end_date_overrides,
        price_history_quarters=price_history_quarters,
        price_fetcher=price_fetcher,
        batch_workers=batch_workers,
        attempts=2,
        phase_label="Phase 3 retry",
    )

    for item in still_deferred:
        logger.error(
            "Skipping %s %s after second pipeline failure: %s",
            ticker_key,
            item.quarter_label,
            item.last_error,
        )
        skipped[item.quarter_label] = _skipped_result(item, item.last_error)

    retry_results.update(skipped)
    return retry_results


def run_historical_batch(
    client: AnthropicClient | None,
    *,
    ticker: str,
    years: int = 10,
    end_quarter: str | None = None,
    quarter_count: int | None = None,
    price_history_quarters: int = BATCH_PRIOR_QUARTER_PRICE_COUNT,
    skip_rescue_judge: bool = True,
    skip_analysis_repair: bool = False,
    fetch: bool = False,
    force_fetch: bool = False,
    dry_run: bool = False,
    fiscal_calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    quarter_end_date_overrides: dict[str, date] | None = None,
    ticker_folder: Path | None = None,
    trim_corpus: bool = True,
    batch_workers: int = DEFAULT_BATCH_WORKERS,
    fetch_workers: int = DEFAULT_FETCH_WORKERS,
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

    clear_history_cache()
    price_fetcher = batch_history_fetcher()
    edgar_client = EdgarClient.from_env() if fetch or force_fetch else None
    results_by_label: dict[str, BatchQuarterResult] = {}

    loaded_by_label, failed_by_label = _fetch_all_quarters(
        quarter_labels=quarter_labels,
        ticker_key=ticker_key,
        folder=folder,
        fetch=fetch,
        force_fetch=force_fetch,
        fiscal_calendars_path=fiscal_calendars_path,
        quarter_end_date_overrides=quarter_end_date_overrides,
        trim_corpus=trim_corpus,
        edgar_client=edgar_client,
        fetch_workers=fetch_workers,
    )
    results_by_label.update(failed_by_label)

    if dry_run or client is None:
        for quarter_label, loaded in loaded_by_label.items():
            bundle = loaded.bundle
            results_by_label[quarter_label] = BatchQuarterResult(
                quarter_label=quarter_label,
                status="success",
                summary=None,
                knowledge_cutoff=bundle.knowledge_cutoff,
                manifest_path=bundle.cache_dir / "manifest.json",
                attempts=1,
                fetch_summary=build_fetch_summary(bundle, ticker=ticker_key),
            )
        return [
            results_by_label[label]
            for label in quarter_labels
            if label in results_by_label
        ]

    score_results, deferred = _run_parallel_scoring(
        client=client,
        loaded_by_label=loaded_by_label,
        quarter_labels=quarter_labels,
        ticker_key=ticker_key,
        skip_rescue_judge=skip_rescue_judge,
        skip_analysis_repair=skip_analysis_repair,
        fiscal_calendars_path=fiscal_calendars_path,
        quarter_end_date_overrides=quarter_end_date_overrides,
        price_history_quarters=price_history_quarters,
        price_fetcher=price_fetcher,
        batch_workers=batch_workers,
        attempts=1,
        phase_label="Phase 2 scoring",
    )
    results_by_label.update(score_results)

    if deferred:
        retry_results = _retry_deferred_parallel(
            client=client,
            deferred=deferred,
            loaded_by_label=loaded_by_label,
            ticker_key=ticker_key,
            folder=folder,
            trim_corpus=trim_corpus,
            fiscal_calendars_path=fiscal_calendars_path,
            quarter_end_date_overrides=quarter_end_date_overrides,
            edgar_client=edgar_client,
            skip_rescue_judge=skip_rescue_judge,
            skip_analysis_repair=skip_analysis_repair,
            price_history_quarters=price_history_quarters,
            price_fetcher=price_fetcher,
            batch_workers=batch_workers,
        )
        results_by_label.update(retry_results)

    return [
        results_by_label[label]
        for label in quarter_labels
        if label in results_by_label
    ]
