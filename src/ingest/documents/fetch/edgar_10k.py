from __future__ import annotations

import logging
from datetime import date, timedelta

from src.ingest.documents.allocation import QuarterAllocation
from src.ingest.documents.fetch.edgar_client import EdgarClient, filing_archive_base
from src.ingest.documents.fetch.edgar_submissions import FilingRecord, find_filings
from src.ingest.documents.fetch.html_text import html_to_text
from src.ingest.documents.models import DocumentType, FetchedDocument

logger = logging.getLogger(__name__)


def _download_filing(
    client: EdgarClient,
    cik: str,
    record: FilingRecord,
    doc_type: DocumentType,
) -> FetchedDocument:
    base = filing_archive_base(cik, record.accession_number)
    url = f"{base}/{record.primary_document}"
    raw = client.get_text(url)
    if record.primary_document.lower().endswith((".htm", ".html")):
        text = html_to_text(raw)
    else:
        text = raw.strip()
    return FetchedDocument(
        doc_type=doc_type,
        text=text,
        accession_number=record.accession_number,
        filing_date=record.filing_date,
        source_url=url,
    )


def fetch_ten_k_primary(
    client: EdgarClient,
    cik: str,
    filings: list[FilingRecord],
    allocation: QuarterAllocation,
    *,
    knowledge_cutoff: date | None = None,
) -> FetchedDocument | None:
    if not allocation.needs_ten_k_primary:
        return None
    if knowledge_cutoff is None:
        return None

    exact = find_filings(
        filings,
        form="10-K",
        report_date=allocation.quarter_end,
        filed_on_or_before=knowledge_cutoff,
    )
    if exact:
        exact.sort(key=lambda record: record.filing_date)
        return _download_filing(client, cik, exact[-1], DocumentType.TEN_K)

    window_end = min(allocation.quarter_end + timedelta(days=120), knowledge_cutoff)
    candidates = find_filings(
        filings,
        form="10-K",
        start=allocation.quarter_end,
        end=window_end,
        filed_on_or_before=knowledge_cutoff,
    )
    if not candidates:
        logger.warning("No 10-K found for fiscal year ending %s", allocation.quarter_end)
        return None
    candidates.sort(key=lambda record: record.filing_date)
    return _download_filing(client, cik, candidates[0], DocumentType.TEN_K)


def fetch_ten_k_context(
    client: EdgarClient,
    cik: str,
    filings: list[FilingRecord],
    allocation: QuarterAllocation,
    *,
    knowledge_cutoff: date | None = None,
) -> FetchedDocument | None:
    if not allocation.needs_ten_k_context:
        return None
    if knowledge_cutoff is None:
        return None

    candidates = find_filings(
        filings,
        form="10-K",
        filed_on_or_before=knowledge_cutoff,
    )
    prior = [
        record
        for record in candidates
        if record.report_date
        and record.report_date < allocation.quarter_end
        and record.filing_date <= knowledge_cutoff
    ]
    if not prior:
        logger.warning(
            "No prior 10-K context found before %s",
            allocation.quarter_end,
        )
        return None
    prior.sort(key=lambda record: record.report_date, reverse=True)
    return _download_filing(client, cik, prior[0], DocumentType.TEN_K_CONTEXT)
