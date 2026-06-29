from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path


class DocumentType(str, Enum):
    EIGHT_K = "eight_k"
    PRESS_RELEASE = "press_release"
    TEN_Q = "ten_q"
    TEN_K = "ten_k"
    TEN_K_CONTEXT = "ten_k_context"
    INVESTOR_PRESENTATION = "investor_presentation"


DOCUMENT_FILENAMES: dict[DocumentType, str] = {
    DocumentType.EIGHT_K: "eight_k.txt",
    DocumentType.PRESS_RELEASE: "press_release.txt",
    DocumentType.TEN_Q: "ten_q.txt",
    DocumentType.TEN_K: "ten_k.txt",
    DocumentType.TEN_K_CONTEXT: "ten_k_context.txt",
    DocumentType.INVESTOR_PRESENTATION: "investor_presentation.txt",
}


@dataclass
class FetchRequest:
    ticker: str
    quarter_label: str


@dataclass
class FetchedDocument:
    doc_type: DocumentType
    text: str
    accession_number: str | None = None
    filing_date: date | None = None
    source_url: str | None = None
    exhibit_name: str | None = None


@dataclass
class QuarterDocumentBundle:
    ticker: str
    quarter_label: str
    cache_dir: Path
    documents: list[FetchedDocument] = field(default_factory=list)

    def get(self, doc_type: DocumentType) -> FetchedDocument | None:
        for doc in self.documents:
            if doc.doc_type == doc_type:
                return doc
        return None

    def corpus_source_text(self) -> str:
        from src.ingest.documents.corpus import build_document_corpus

        return build_document_corpus(self)


class DocumentFetchError(Exception):
    pass


class DocumentLoadError(Exception):
    pass
