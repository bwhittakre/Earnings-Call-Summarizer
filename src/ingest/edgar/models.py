from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path


class EdgarFetchError(Exception):
    pass


@dataclass(frozen=True)
class FilingRef:
    form: str
    accession_number: str
    filing_date: date
    report_date: date | None
    primary_document: str
    source_url: str


@dataclass(frozen=True)
class PlannedDocument:
    doc_type: str
    filename: str
    filing: FilingRef


@dataclass(frozen=True)
class QuarterFetchPlan:
    ticker: str
    quarter: str
    fiscal_year: str
    period_end: date
    as_of_date_text: str
    company_name: str
    folder: Path
    documents: tuple[PlannedDocument, ...]
    is_q4: bool


@dataclass
class FetchedDocument:
    doc_type: str
    filename: str
    filing: FilingRef
    text: str
    char_count: int


@dataclass
class FetchResult:
    plan: QuarterFetchPlan
    documents: list[FetchedDocument] = field(default_factory=list)
    skipped: bool = False
    warnings: list[str] = field(default_factory=list)
