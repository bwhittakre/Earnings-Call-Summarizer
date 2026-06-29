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
from src.ingest.documents.fetch.edgar_8k import fetch_eight_k_bundle
from src.ingest.documents.fetch.edgar_10k import fetch_ten_k_context, fetch_ten_k_primary
from src.ingest.documents.fetch.edgar_10q import fetch_ten_q
from src.ingest.documents.fetch.edgar_client import EdgarClient, fetch_submissions, normalize_cik
from src.ingest.documents.fetch.ir_presentations import fetch_ir_presentation
from src.ingest.documents.models import DocumentFetchError, FetchRequest, QuarterDocumentBundle
from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH

logger = logging.getLogger(__name__)


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
    submissions = fetch_submissions(edgar_client, cik)

    eight_k_result = fetch_eight_k_bundle(edgar_client, cik, submissions, allocation)
    documents = []
    if eight_k_result.eight_k:
        documents.append(eight_k_result.eight_k)
    if eight_k_result.press_release:
        documents.append(eight_k_result.press_release)
    if eight_k_result.investor_presentation:
        documents.append(eight_k_result.investor_presentation)

    ten_q = fetch_ten_q(edgar_client, cik, submissions, allocation)
    if ten_q:
        documents.append(ten_q)

    ten_k = fetch_ten_k_primary(edgar_client, cik, submissions, allocation)
    if ten_k:
        documents.append(ten_k)

    ten_k_context = fetch_ten_k_context(edgar_client, cik, submissions, allocation)
    if ten_k_context:
        documents.append(ten_k_context)

    if not any(
        doc.doc_type.value == "investor_presentation"
        for doc in documents
    ):
        ir_doc = fetch_ir_presentation(
            edgar_client,
            ticker,
            ticker_config.get("ir_provider"),
            request,
        )
        if ir_doc:
            documents.append(ir_doc)

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
    )
    save_bundle(bundle)
    logger.info(
        "Saved %s documents for %s %s to %s",
        len(documents),
        ticker,
        allocation.quarter_label,
        bundle.cache_dir,
    )
    return bundle
