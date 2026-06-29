from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

from src.ingest.documents.allocation import allocate_quarter
from src.ingest.documents.cache import (
    bundle_is_cached,
    load_bundle_from_cache,
    quarter_cache_dir,
    save_bundle,
    ticker_documents_folder,
)
from src.ingest.documents.config import resolve_ticker_config
from src.ingest.documents.corpus_trim import trim_document_text
from src.ingest.documents.fetch.edgar_8k import fetch_eight_k_bundle
from src.ingest.documents.fetch.edgar_10k import fetch_ten_k_context, fetch_ten_k_primary
from src.ingest.documents.fetch.edgar_10q import fetch_ten_q
from src.ingest.documents.fetch.edgar_client import EdgarClient, normalize_cik
from src.ingest.documents.fetch.edgar_submissions import load_all_filings
from src.ingest.documents.fetch.filings_cache import get_ticker_filings
from src.ingest.documents.fetch.ir_presentations import fetch_ir_presentation
from src.ingest.documents.models import DocumentFetchError, FetchRequest, QuarterDocumentBundle
from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH

logger = logging.getLogger(__name__)

IR_PRESENTATION_FETCH_ENABLED = False


def _apply_trim_to_bundle(bundle: QuarterDocumentBundle) -> QuarterDocumentBundle:
    for doc in bundle.documents:
        doc.text = trim_document_text(doc)
    bundle.corpus_trimmed = True
    save_bundle(bundle)
    return bundle


def fetch_quarter_documents(
    request: FetchRequest,
    *,
    force: bool = False,
    ticker_folder: Path | None = None,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    date_overrides: dict[str, date] | None = None,
    client: EdgarClient | None = None,
) -> QuarterDocumentBundle:
    ticker = request.ticker.strip().upper()
    quarter_label = request.quarter_label
    folder = ticker_folder or ticker_documents_folder(ticker)

    if not force and bundle_is_cached(ticker, quarter_label, ticker_folder=folder):
        cached = load_bundle_from_cache(ticker, quarter_label, ticker_folder=folder)
        if cached:
            if request.trim_corpus and not cached.corpus_trimmed:
                logger.info(
                    "Trimming cached document bundle at %s (avoiding refetch)",
                    cached.cache_dir,
                )
                return _apply_trim_to_bundle(cached)
            logger.info("Using cached document bundle at %s", cached.cache_dir)
            return cached

    ticker_config = resolve_ticker_config(ticker)
    cik = normalize_cik(str(ticker_config["cik"]))
    edgar_client = client or EdgarClient.from_env()
    allocation = allocate_quarter(
        ticker,
        quarter_label,
        calendars_path=calendars_path,
        date_overrides=date_overrides,
    )
    filings = get_ticker_filings(
        edgar_client,
        cik,
        folder,
        force_refresh=force,
    )

    eight_k_result = fetch_eight_k_bundle(
        edgar_client,
        cik,
        filings,
        allocation,
    )
    if eight_k_result.eight_k is None or eight_k_result.knowledge_cutoff is None:
        raise DocumentFetchError(
            f"No earnings 8-K found for {ticker} {quarter_label} "
            f"in window ending {allocation.earnings_window_end}."
        )

    knowledge_cutoff = eight_k_result.knowledge_cutoff
    documents = []
    documents.append(eight_k_result.eight_k)
    if eight_k_result.press_release:
        documents.append(eight_k_result.press_release)
    if eight_k_result.cfo_commentary:
        documents.append(eight_k_result.cfo_commentary)
    if eight_k_result.investor_presentation:
        documents.append(eight_k_result.investor_presentation)

    ten_q = fetch_ten_q(
        edgar_client,
        cik,
        filings,
        allocation,
        knowledge_cutoff=knowledge_cutoff,
    )
    if ten_q:
        documents.append(ten_q)

    ten_k = fetch_ten_k_primary(
        edgar_client,
        cik,
        filings,
        allocation,
        knowledge_cutoff=knowledge_cutoff,
    )
    if ten_k:
        documents.append(ten_k)

    ten_k_context = fetch_ten_k_context(
        edgar_client,
        cik,
        filings,
        allocation,
        knowledge_cutoff=knowledge_cutoff,
    )
    if ten_k_context:
        documents.append(ten_k_context)

    if not any(
        doc.doc_type.value == "investor_presentation"
        for doc in documents
    ) and IR_PRESENTATION_FETCH_ENABLED:
        ir_doc = fetch_ir_presentation(
            edgar_client,
            ticker,
            ticker_config.get("ir_provider"),
            request,
        )
        if ir_doc:
            documents.append(ir_doc)

    if eight_k_result.transcript_text:
        from src.enrichment.transcript_cache import write_transcript_cache
        from src.paths import DEFAULT_TRANSCRIPTS_ROOT

        write_transcript_cache(
            ticker,
            allocation.quarter_label,
            eight_k_result.transcript_text,
            source="sec_8k_exhibit",
            url=eight_k_result.transcript_url,
            root=DEFAULT_TRANSCRIPTS_ROOT,
        )
        logger.info(
            "Cached earnings call transcript for %s %s from 8-K exhibit",
            ticker,
            allocation.quarter_label,
        )

    if request.trim_corpus:
        for doc in documents:
            doc.text = trim_document_text(doc)

    if not documents:
        raise DocumentFetchError(
            f"No documents fetched for {ticker} {quarter_label}. "
            "Check ticker config, quarter label, and SEC filing availability."
        )

    bundle = QuarterDocumentBundle(
        ticker=ticker,
        quarter_label=allocation.quarter_label,
        cache_dir=quarter_cache_dir(
            ticker,
            allocation.quarter_label,
            ticker_folder=folder,
        ),
        documents=documents,
        knowledge_cutoff=knowledge_cutoff,
        corpus_trimmed=request.trim_corpus,
    )
    save_bundle(bundle)
    logger.info(
        "Saved %s documents for %s %s to %s (cutoff=%s)",
        len(documents),
        ticker,
        allocation.quarter_label,
        bundle.cache_dir,
        knowledge_cutoff.isoformat(),
    )
    return bundle
