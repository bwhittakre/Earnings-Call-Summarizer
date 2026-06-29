from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date

from src.ingest.documents.allocation import QuarterAllocation
from src.ingest.documents.fetch.edgar_client import EdgarClient, filing_archive_base
from src.ingest.documents.fetch.edgar_submissions import FilingRecord, find_filings
from src.ingest.documents.fetch.html_text import html_to_text
from src.ingest.documents.models import DocumentType, FetchedDocument

logger = logging.getLogger(__name__)

_PRESS_RELEASE_PATTERN = re.compile(
    r"press\s+release|earnings\s+release|results",
    re.IGNORECASE,
)
_PRESENTATION_PATTERN = re.compile(
    r"presentation|investor\s+deck|slide",
    re.IGNORECASE,
)
_COMMENTARY_PATTERN = re.compile(
    r"cfo\s+commentary|commentary",
    re.IGNORECASE,
)
_TRANSCRIPT_PATTERN = re.compile(
    r"transcript|conference\s+call|earnings\s+call",
    re.IGNORECASE,
)


@dataclass
class EightKFetchResult:
    eight_k: FetchedDocument | None = None
    press_release: FetchedDocument | None = None
    investor_presentation: FetchedDocument | None = None
    knowledge_cutoff: date | None = None


def _load_filing_index(client: EdgarClient, cik: str, record: FilingRecord) -> list[dict]:
    base = filing_archive_base(cik, record.accession_number)
    for index_name in ("index.json", f"{record.accession_number}-index.json"):
        index_url = f"{base}/{index_name}"
        try:
            payload = client.get_json(index_url)
        except Exception:
            continue
        items = payload.get("directory", {}).get("item", [])
        if isinstance(items, dict):
            items = [items]
        if items:
            return items
    logger.warning("Could not load filing index for %s", record.accession_number)
    return []


def _download_exhibit_text(
    client: EdgarClient,
    cik: str,
    record: FilingRecord,
    filename: str,
) -> tuple[str, str]:
    base = filing_archive_base(cik, record.accession_number)
    url = f"{base}/{filename}"
    raw = client.get_text(url)
    if filename.lower().endswith((".htm", ".html")):
        return html_to_text(raw), url
    return raw.strip(), url


def _download_primary_text(
    client: EdgarClient,
    cik: str,
    record: FilingRecord,
) -> tuple[str, str]:
    return _download_exhibit_text(client, cik, record, record.primary_document)


def _classify_exhibit(description: str, filename: str) -> str | None:
    combined = f"{description} {filename}"
    if _PRESENTATION_PATTERN.search(combined):
        return "presentation"
    if _PRESS_RELEASE_PATTERN.search(combined):
        return "press_release"
    if _COMMENTARY_PATTERN.search(combined):
        return "commentary"
    if _TRANSCRIPT_PATTERN.search(combined):
        return "transcript"
    return None


def find_item_202_8k(
    filings: list[FilingRecord],
    allocation: QuarterAllocation,
    *,
    knowledge_cutoff: date | None = None,
) -> FilingRecord | None:
    window_end = allocation.earnings_window_end
    if knowledge_cutoff is not None:
        window_end = min(window_end, knowledge_cutoff)
    matches = find_filings(
        filings,
        form="8-K",
        start=allocation.earnings_window_start,
        end=window_end,
        item_contains="2.02",
        filed_on_or_before=knowledge_cutoff,
    )
    if not matches:
        matches = find_filings(
            filings,
            form="8-K",
            start=allocation.earnings_window_start,
            end=window_end,
            filed_on_or_before=knowledge_cutoff,
        )
    if not matches:
        return None
    matches.sort(key=lambda record: record.filing_date)
    return matches[0]


def fetch_eight_k_bundle(
    client: EdgarClient,
    cik: str,
    filings: list[FilingRecord],
    allocation: QuarterAllocation,
    *,
    knowledge_cutoff: date | None = None,
) -> EightKFetchResult:
    record = find_item_202_8k(
        filings,
        allocation,
        knowledge_cutoff=knowledge_cutoff,
    )
    if not record:
        logger.warning(
            "No 8-K found for %s in earnings window %s to %s",
            allocation.quarter_label,
            allocation.earnings_window_start,
            allocation.earnings_window_end,
        )
        return EightKFetchResult()

    cutoff = record.filing_date
    primary_text, primary_url = _download_primary_text(client, cik, record)
    eight_k = FetchedDocument(
        doc_type=DocumentType.EIGHT_K,
        text=primary_text,
        accession_number=record.accession_number,
        filing_date=record.filing_date,
        source_url=primary_url,
    )

    press_release: FetchedDocument | None = None
    presentation: FetchedDocument | None = None
    index_items = _load_filing_index(client, cik, record)
    for item in index_items:
        name = str(item.get("name", ""))
        description = str(item.get("description", ""))
        if not name or name == record.primary_document:
            continue
        if not name.lower().endswith((".htm", ".html", ".txt")):
            continue
        kind = _classify_exhibit(description, name)
        try:
            text, url = _download_exhibit_text(client, cik, record, name)
        except Exception:
            logger.warning("Failed to download exhibit %s", name)
            continue
        if kind == "press_release" and press_release is None:
            press_release = FetchedDocument(
                doc_type=DocumentType.PRESS_RELEASE,
                text=text,
                accession_number=record.accession_number,
                filing_date=record.filing_date,
                source_url=url,
                exhibit_name=name,
            )
        elif kind == "presentation" and presentation is None:
            presentation = FetchedDocument(
                doc_type=DocumentType.INVESTOR_PRESENTATION,
                text=text,
                accession_number=record.accession_number,
                filing_date=record.filing_date,
                source_url=url,
                exhibit_name=name,
            )

    if press_release is None:
        for item in index_items:
            name = str(item.get("name", ""))
            description = str(item.get("description", ""))
            if "99.1" in name or _PRESS_RELEASE_PATTERN.search(description):
                try:
                    text, url = _download_exhibit_text(client, cik, record, name)
                except Exception:
                    continue
                press_release = FetchedDocument(
                    doc_type=DocumentType.PRESS_RELEASE,
                    text=text,
                    accession_number=record.accession_number,
                    filing_date=record.filing_date,
                    source_url=url,
                    exhibit_name=name,
                )
                break

    return EightKFetchResult(
        eight_k=eight_k,
        press_release=press_release,
        investor_presentation=presentation,
        knowledge_cutoff=cutoff,
    )


def fetch_transcript_exhibit(
    client: EdgarClient,
    cik: str,
    record: FilingRecord,
) -> tuple[str, str] | None:
    index_items = _load_filing_index(client, cik, record)
    for item in index_items:
        name = str(item.get("name", ""))
        description = str(item.get("description", ""))
        if not name or name == record.primary_document:
            continue
        if not name.lower().endswith((".htm", ".html", ".txt")):
            continue
        if _classify_exhibit(description, name) != "transcript":
            continue
        try:
            text, url = _download_exhibit_text(client, cik, record, name)
        except Exception:
            logger.warning("Failed to download transcript exhibit %s", name)
            continue
        if text.strip():
            return text, url
    return None
