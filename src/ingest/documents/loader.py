from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.ingest.documents.cache import (
    load_bundle_from_cache,
    quarter_cache_dir,
    ticker_documents_folder,
)
from src.ingest.documents.corpus import build_document_corpus, corpus_section_labels
from src.ingest.documents.models import DocumentLoadError, QuarterDocumentBundle
from src.ingest.loader import normalize_quarter_label


@dataclass
class LoadedQuarterDocuments:
    bundle: QuarterDocumentBundle
    corpus_text: str
    quarter_label: str
    audit_label: str


def document_audit_label(ticker: str, quarter_label: str) -> str:
    return f"{ticker}_{quarter_label}_documents"


def resolve_ticker_folder(documents_path: Path, ticker: str) -> Path:
    slug = ticker.strip().lower()
    if documents_path.name.lower() == slug:
        return documents_path
    if (documents_path / slug).is_dir():
        return documents_path / slug
    return documents_path


def load_quarter_documents(
    documents_path: Path,
    *,
    ticker: str,
    quarter: str,
    ticker_folder: Path | None = None,
) -> LoadedQuarterDocuments:
    normalized_quarter = normalize_quarter_label(quarter)
    folder = ticker_folder or resolve_ticker_folder(documents_path, ticker)
    bundle = load_bundle_from_cache(
        ticker,
        normalized_quarter,
        ticker_folder=folder,
    )
    if bundle is None:
        bundle_dir = quarter_cache_dir(
            ticker,
            normalized_quarter,
            ticker_folder=folder,
        )
        raise DocumentLoadError(
            f"No cached document bundle at {bundle_dir}. Use --fetch to download SEC filings."
        )
    corpus_text = build_document_corpus(bundle)
    if not corpus_text.strip():
        raise DocumentLoadError(f"Document bundle for {normalized_quarter} is empty.")
    return LoadedQuarterDocuments(
        bundle=bundle,
        corpus_text=corpus_text,
        quarter_label=normalized_quarter,
        audit_label=document_audit_label(ticker.upper(), normalized_quarter),
    )


def dry_run_documents_report(
    documents_path: Path,
    *,
    ticker: str,
    quarter: str,
) -> str:
    folder = resolve_ticker_folder(documents_path, ticker)
    loaded = load_quarter_documents(
        documents_path,
        ticker=ticker,
        quarter=quarter,
        ticker_folder=folder,
    )
    sections = corpus_section_labels(loaded.bundle)
    lines = [
        f"Document bundle: {loaded.bundle.cache_dir}",
        f"Quarter: {loaded.quarter_label}",
        f"Ticker: {loaded.bundle.ticker}",
        f"Sections ({len(sections)}): {', '.join(sections) if sections else 'none'}",
        f"Corpus size: {len(loaded.corpus_text)} characters",
    ]
    for doc in loaded.bundle.documents:
        lines.append(
            f"  - {doc.doc_type.value}: {len(doc.text)} chars"
            + (f" ({doc.accession_number})" if doc.accession_number else "")
        )
    return "\n".join(lines)
