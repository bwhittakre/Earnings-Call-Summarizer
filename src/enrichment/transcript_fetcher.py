from __future__ import annotations

import logging
from pathlib import Path

from src.enrichment.models import TranscriptSource
from src.enrichment.transcript_cache import read_cached_transcript, write_transcript_cache
from src.ingest.documents.cache import ticker_documents_folder
from src.ingest.documents.config import resolve_ticker_config
from src.ingest.documents.fetch.edgar_8k import fetch_transcript_exhibit
from src.ingest.documents.fetch.edgar_client import EdgarClient, fetch_submissions, normalize_cik
from src.ingest.documents.fetch.edgar_submissions import load_all_filings
from src.ingest.documents.loader import load_quarter_documents
from src.ingest.documents.models import DocumentType
from src.paths import DEFAULT_TRANSCRIPTS_ROOT

logger = logging.getLogger(__name__)


def _fetch_from_sec_exhibits(
    ticker: str,
    quarter_label: str,
    *,
    transcripts_root: Path = DEFAULT_TRANSCRIPTS_ROOT,
) -> TranscriptSource | None:
    ticker_key = ticker.strip().upper()
    folder = ticker_documents_folder(ticker_key)
    try:
        loaded = load_quarter_documents(
            folder,
            ticker=ticker_key,
            quarter=quarter_label,
            ticker_folder=folder,
        )
    except Exception as exc:
        logger.debug("Cannot load Edgar bundle for transcript fetch %s: %s", quarter_label, exc)
        return None

    bundle = loaded.bundle
    eight_k_doc = next(
        (doc for doc in bundle.documents if doc.doc_type == DocumentType.EIGHT_K),
        None,
    )
    if not eight_k_doc or not eight_k_doc.accession_number:
        return None

    client = EdgarClient.from_env()
    ticker_config = resolve_ticker_config(ticker_key)
    cik = normalize_cik(str(ticker_config["cik"]))
    submissions = fetch_submissions(client, cik)
    filings = load_all_filings(submissions, client, cik)
    record = next(
        (
            filing
            for filing in filings
            if filing.accession_number == eight_k_doc.accession_number
        ),
        None,
    )
    if record is None:
        return None

    fetched = fetch_transcript_exhibit(client, cik, record)
    if fetched is None:
        return None
    text, url = fetched
    write_transcript_cache(
        ticker_key,
        quarter_label,
        text,
        source="sec_8k_exhibit",
        url=url,
        root=transcripts_root,
    )
    return TranscriptSource(
        quarter=quarter_label,
        text=text,
        source="sec_8k_exhibit",
        url=url,
    )


def fetch_transcript(
    ticker: str,
    quarter_label: str,
    *,
    transcripts_root: Path = DEFAULT_TRANSCRIPTS_ROOT,
    allow_web_discovery: bool = False,
) -> TranscriptSource | None:
    ticker_key = ticker.strip().upper()
    cached = read_cached_transcript(ticker_key, quarter_label, transcripts_root)
    if cached:
        text, manifest = cached
        if text.strip():
            return TranscriptSource(
                quarter=quarter_label,
                text=text,
                source=str(manifest.get("source", "local_cache")),
                url=manifest.get("url"),
                fetched_at=manifest.get("fetched_at"),
            )

    sec_source = _fetch_from_sec_exhibits(
        ticker_key,
        quarter_label,
        transcripts_root=transcripts_root,
    )
    if sec_source is not None:
        return sec_source

    if allow_web_discovery:
        from src.enrichment.web_discovery import discover_transcript_url

        url = discover_transcript_url(ticker_key, quarter_label)
        if url:
            logger.info("Web discovery found URL for %s (not fetched in v1 stub)", url)

    return None
