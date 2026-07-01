from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Literal


class FilingLoadError(Exception):
    pass


ExcerptMode = Literal["smart", "full", "off"]
DEFAULT_EXCERPT_MODE: ExcerptMode = "smart"


class DocumentType(str, Enum):
    TEN_K = "10-K"
    TEN_Q = "10-Q"
    EIGHT_K = "8-K"
    PRESS_RELEASE = "PRESS_RELEASE"
    INVESTOR_PRESENTATION = "INVESTOR_PRESENTATION"


DOCUMENT_BASENAMES: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.TEN_K: ("10-K", "10-k"),
    DocumentType.TEN_Q: ("10-Q", "10-q"),
    DocumentType.EIGHT_K: ("8-K", "8-k"),
    DocumentType.PRESS_RELEASE: ("press_release", "press-release", "earnings_release"),
    DocumentType.INVESTOR_PRESENTATION: (
        "investor_presentation",
        "investor-presentation",
        "investor_deck",
    ),
}


EVENT_DOCUMENT_TYPES = (
    DocumentType.EIGHT_K,
    DocumentType.PRESS_RELEASE,
    DocumentType.INVESTOR_PRESENTATION,
)


@dataclass
class LoadedDocument:
    doc_type: DocumentType
    quarter_label: str | None
    path: Path
    text: str
    section_label: str | None = None


@dataclass
class FilingPackage:
    ticker: str
    quarter: str
    folder: Path
    company_name: str | None
    fiscal_year: str | None
    as_of_date: date | None
    as_of_date_text: str | None
    documents: dict[str, LoadedDocument]
    raw_corpus_text: str
    analysis_corpus_text: str
    corpus_text: str
    excerpt_stats: dict
    is_q4: bool
    warnings: list[str] = field(default_factory=list)

    def audit_label(self) -> str:
        return f"{self.ticker}_{self.quarter}"
