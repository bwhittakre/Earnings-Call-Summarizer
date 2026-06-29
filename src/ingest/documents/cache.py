from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from src.ingest.documents.models import (
    DOCUMENT_FILENAMES,
    DocumentType,
    FetchedDocument,
    QuarterDocumentBundle,
)
from src.paths import DEFAULT_DOCUMENTS_ROOT


def ticker_cache_slug(ticker: str) -> str:
    return ticker.strip().lower()


def quarter_cache_dir(
    ticker: str,
    quarter_label: str,
    documents_root: Path = DEFAULT_DOCUMENTS_ROOT,
    *,
    ticker_folder: Path | None = None,
) -> Path:
    base = ticker_folder if ticker_folder is not None else documents_root / ticker_cache_slug(ticker)
    return base / quarter_label


def ticker_documents_folder(
    ticker: str,
    documents_root: Path = DEFAULT_DOCUMENTS_ROOT,
    *,
    ticker_folder: Path | None = None,
) -> Path:
    if ticker_folder is not None:
        return ticker_folder
    return documents_root / ticker_cache_slug(ticker)


def _serialize_document(doc: FetchedDocument) -> dict:
    return {
        "doc_type": doc.doc_type.value,
        "accession_number": doc.accession_number,
        "filing_date": doc.filing_date.isoformat() if doc.filing_date else None,
        "source_url": doc.source_url,
        "exhibit_name": doc.exhibit_name,
        "filename": DOCUMENT_FILENAMES[doc.doc_type],
        "char_count": len(doc.text),
    }


def save_bundle(bundle: QuarterDocumentBundle) -> Path:
    cache_dir = bundle.cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "ticker": bundle.ticker,
        "quarter_label": bundle.quarter_label,
        "knowledge_cutoff": (
            bundle.knowledge_cutoff.isoformat() if bundle.knowledge_cutoff else None
        ),
        "corpus_trimmed": bundle.corpus_trimmed,
        "documents": [],
    }
    for doc in bundle.documents:
        filename = DOCUMENT_FILENAMES[doc.doc_type]
        (cache_dir / filename).write_text(doc.text, encoding="utf-8")
        manifest["documents"].append(_serialize_document(doc))
    (cache_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return cache_dir


def load_bundle_from_cache(
    ticker: str,
    quarter_label: str,
    documents_root: Path = DEFAULT_DOCUMENTS_ROOT,
    *,
    ticker_folder: Path | None = None,
) -> QuarterDocumentBundle | None:
    cache_dir = quarter_cache_dir(
        ticker,
        quarter_label,
        documents_root,
        ticker_folder=ticker_folder,
    )
    manifest_path = cache_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    knowledge_cutoff = None
    if manifest.get("knowledge_cutoff"):
        knowledge_cutoff = date.fromisoformat(manifest["knowledge_cutoff"])
    documents: list[FetchedDocument] = []
    for entry in manifest.get("documents", []):
        doc_type = DocumentType(entry["doc_type"])
        filename = entry.get("filename") or DOCUMENT_FILENAMES[doc_type]
        text_path = cache_dir / filename
        if not text_path.exists():
            continue
        filing_date = None
        if entry.get("filing_date"):
            filing_date = date.fromisoformat(entry["filing_date"])
        documents.append(
            FetchedDocument(
                doc_type=doc_type,
                text=text_path.read_text(encoding="utf-8", errors="replace"),
                accession_number=entry.get("accession_number"),
                filing_date=filing_date,
                source_url=entry.get("source_url"),
                exhibit_name=entry.get("exhibit_name"),
            )
        )
    if not documents:
        return None
    return QuarterDocumentBundle(
        ticker=ticker.upper(),
        quarter_label=quarter_label,
        cache_dir=cache_dir,
        documents=documents,
        knowledge_cutoff=knowledge_cutoff,
        corpus_trimmed=bool(manifest.get("corpus_trimmed")),
    )


def bundle_is_cached(
    ticker: str,
    quarter_label: str,
    documents_root: Path = DEFAULT_DOCUMENTS_ROOT,
    *,
    ticker_folder: Path | None = None,
) -> bool:
    cache_dir = quarter_cache_dir(
        ticker,
        quarter_label,
        documents_root,
        ticker_folder=ticker_folder,
    )
    return (cache_dir / "manifest.json").exists()
