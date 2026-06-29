from __future__ import annotations

import logging
from datetime import timedelta

from src.ingest.documents.allocation import QuarterAllocation
from src.ingest.documents.fetch.edgar_client import EdgarClient, filing_archive_base
from src.ingest.documents.fetch.edgar_submissions import find_filings
from src.ingest.documents.fetch.html_text import html_to_text
from src.ingest.documents.models import DocumentType, FetchedDocument

logger = logging.getLogger(__name__)


def _download_periodic_filing(
    client: EdgarClient,
    cik: str,
    record,
) -> FetchedDocument:
    base = filing_archive_base(cik, record.accession_number)
    url = f"{base}/{record.primary_document}"
    raw = client.get_text(url)
    if record.primary_document.lower().endswith((".htm", ".html")):
        text = html_to_text(raw)
    else:
        text = raw.strip()
    return FetchedDocument(
        doc_type=DocumentType.TEN_Q,
        text=text,
        accession_number=record.accession_number,
        filing_date=record.filing_date,
        source_url=url,
    )


def fetch_ten_q(
    client: EdgarClient,
    cik: str,
    submissions: dict,
    allocation: QuarterAllocation,
) -> FetchedDocument | None:
    if not allocation.needs_ten_q:
        return None

    exact = find_filings(
        submissions,
        form="10-Q",
        report_date=allocation.quarter_end,
    )
    if exact:
        doc = _download_periodic_filing(client, cik, exact[0])
        doc.doc_type = DocumentType.TEN_Q
        return doc

    window_end = allocation.quarter_end + timedelta(days=120)
    candidates = find_filings(
        submissions,
        form="10-Q",
        start=allocation.quarter_end,
        end=window_end,
    )
    if not candidates:
        logger.warning("No 10-Q found for quarter ending %s", allocation.quarter_end)
        return None
    def _distance_days(record) -> int:
        anchor = record.report_date or record.filing_date
        return abs((anchor - allocation.quarter_end).days)

    candidates.sort(key=_distance_days)
    doc = _download_periodic_filing(client, cik, candidates[0])
    doc.doc_type = DocumentType.TEN_Q
    return doc
