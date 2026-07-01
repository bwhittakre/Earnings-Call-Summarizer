from __future__ import annotations

import re
from dataclasses import dataclass, field

from src.ingest.filings.sec_sections import SecSection, select_sections_for_doc
from src.ingest.filings.types import DocumentType, LoadedDocument

DEFAULT_MAX_ANALYSIS_CHARS = 400_000
SMALL_DOC_PASS_THROUGH_CHARS = 80_000
EXCERPT_SEPARATOR = "\n\n---\n\n"

BOOST_TERMS = (
    "revenue",
    "guidance",
    "outlook",
    "expect",
    "forecast",
    "margin",
    "gross",
    "operating",
    "eps",
    "earnings",
    "data center",
    "cloud",
    "growth",
    "yoy",
    "year over year",
    "quarter over quarter",
    "sequential",
    "demand",
    "supply",
    "segment",
    "blackwell",
    "capex",
    "buyback",
    "dividend",
    "cash flow",
    "inventory",
    "headwind",
    "tailwind",
    "risk",
    "export",
    "china",
)

PENALIZE_TERMS = (
    "forward-looking statements",
    "safe harbor",
    "table of contents",
    "exhibit",
    "certification",
    "signatures",
    "pursuant to section 906",
    "pursuant to rule 13a",
    "xbrli:",
    "unaudited condensed consolidated",
    "principles of consolidation",
)


@dataclass
class PulledExcerpt:
    text: str
    section_item: str
    score: float


@dataclass
class DocumentExcerptResult:
    doc_key: str
    doc_type: DocumentType
    quarter_label: str | None
    section_label: str | None
    raw_chars: int
    excerpt_chars: int
    excerpt_count: int
    excerpts: list[str] = field(default_factory=list)


@dataclass
class ExcerptPullResult:
    documents: list[DocumentExcerptResult]
    total_raw_chars: int
    total_excerpt_chars: int
    total_excerpt_count: int


def split_paragraphs(text: str) -> list[str]:
    parts = re.split(r"\n\s*\n+", text)
    paragraphs: list[str] = []
    for part in parts:
        stripped = part.strip()
        if len(stripped) >= 40:
            paragraphs.append(stripped)
    return paragraphs


def score_paragraph(paragraph: str, *, is_first_mda: bool = False) -> float:
    lower = paragraph.lower()
    score = 0.0
    if is_first_mda:
        score += 50.0
    if re.search(r"\$[\d,]+|\d+(?:\.\d+)?%|\d+(?:\.\d+)?\s*(?:billion|million|bn|mm)\b", lower):
        score += 25.0
    if re.search(r"\byoy\b|year over year|quarter over quarter|sequential", lower):
        score += 15.0
    for term in BOOST_TERMS:
        if term in lower:
            score += 8.0
    for term in PENALIZE_TERMS:
        if term in lower:
            score -= 20.0
    if re.fullmatch(r"[\d\s.\-]+", paragraph.strip()):
        score -= 30.0
    if len(paragraph) > 4000:
        score -= 5.0
    return score


def select_paragraphs_from_section(
    section: SecSection,
    source_text: str,
    budget: int,
    *,
    anchor_first: bool = False,
) -> list[PulledExcerpt]:
    paragraphs = split_paragraphs(section.text)
    if not paragraphs:
        if section.text.strip() and len(section.text) <= budget:
            return [
                PulledExcerpt(
                    text=section.text.strip(),
                    section_item=section.item_id,
                    score=0.0,
                )
            ]
        return []

    scored: list[tuple[float, int, str]] = []
    for index, paragraph in enumerate(paragraphs):
        is_first = anchor_first and section.item_id in {"2", "7"} and index == 0
        scored.append(
            (score_paragraph(paragraph, is_first_mda=is_first), index, paragraph)
        )

    selected: list[PulledExcerpt] = []
    used_chars = 0

    if anchor_first and section.item_id in {"2", "7"} and paragraphs:
        first = paragraphs[0]
        if first in source_text:
            selected.append(
                PulledExcerpt(text=first, section_item=section.item_id, score=999.0)
            )
            used_chars += len(first)

    for score, _, paragraph in sorted(scored, key=lambda row: (-row[0], row[1])):
        if paragraph in {item.text for item in selected}:
            continue
        if paragraph not in source_text:
            continue
        extra = len(paragraph) + (len(EXCERPT_SEPARATOR) if selected else 0)
        if used_chars + extra > budget:
            continue
        selected.append(
            PulledExcerpt(text=paragraph, section_item=section.item_id, score=score)
        )
        used_chars += extra
    return selected


def _document_pass_through(doc: LoadedDocument) -> DocumentExcerptResult:
    return DocumentExcerptResult(
        doc_key=_doc_key(doc),
        doc_type=doc.doc_type,
        quarter_label=doc.quarter_label,
        section_label=doc.section_label,
        raw_chars=len(doc.text),
        excerpt_chars=len(doc.text),
        excerpt_count=1,
        excerpts=[doc.text.strip()],
    )


def _doc_key(doc: LoadedDocument) -> str:
    if doc.doc_type == DocumentType.EIGHT_K:
        label = doc.section_label or doc.path.stem
        return f"8-K:{label}"
    return f"{doc.doc_type.value}:{doc.quarter_label or ''}"


def _allocate_budgets(
    documents: list[LoadedDocument],
    *,
    max_analysis_chars: int,
    primary_quarter: str,
) -> dict[str, int]:
    keys = [_doc_key(doc) for doc in documents]
    budgets = {key: 0 for key in keys}

    small_docs: list[LoadedDocument] = []
    primary_docs: list[LoadedDocument] = []
    sibling_docs: list[LoadedDocument] = []

    for doc in documents:
        if doc.doc_type in {
            DocumentType.EIGHT_K,
            DocumentType.PRESS_RELEASE,
            DocumentType.INVESTOR_PRESENTATION,
        }:
            small_docs.append(doc)
        elif doc.doc_type == DocumentType.TEN_Q and doc.quarter_label != primary_quarter:
            sibling_docs.append(doc)
        else:
            primary_docs.append(doc)

    remaining = max_analysis_chars
    for doc in small_docs:
        key = _doc_key(doc)
        allocation = min(len(doc.text), SMALL_DOC_PASS_THROUGH_CHARS, remaining)
        budgets[key] = max(allocation, min(len(doc.text), remaining))
        remaining -= budgets[key]

    if primary_docs and remaining > 0:
        primary_budget = int(remaining * 0.5)
        per_primary = max(primary_budget // len(primary_docs), 10_000)
        for doc in primary_docs:
            key = _doc_key(doc)
            budgets[key] = min(per_primary, remaining)
            remaining -= budgets[key]

    if sibling_docs and remaining > 0:
        per_sibling = max(remaining // len(sibling_docs), 5_000)
        for doc in sibling_docs:
            key = _doc_key(doc)
            budgets[key] = min(per_sibling, remaining)
            remaining -= budgets[key]

    if remaining > 0 and primary_docs:
        key = _doc_key(primary_docs[0])
        budgets[key] += remaining

    return budgets


def pull_excerpts_from_document(
    doc: LoadedDocument,
    *,
    budget: int,
    primary_quarter: str,
) -> DocumentExcerptResult:
    raw_chars = len(doc.text)
    key = _doc_key(doc)

    if doc.doc_type in {
        DocumentType.EIGHT_K,
        DocumentType.PRESS_RELEASE,
        DocumentType.INVESTOR_PRESENTATION,
    } and raw_chars <= SMALL_DOC_PASS_THROUGH_CHARS:
        return _document_pass_through(doc)

    is_prior = (
        doc.doc_type == DocumentType.TEN_Q
        and doc.quarter_label is not None
        and doc.quarter_label != primary_quarter
    )
    sections = select_sections_for_doc(
        doc.text,
        doc.doc_type,
        is_prior_quarter_ten_q=is_prior,
    )

    pulled: list[PulledExcerpt] = []
    if not sections:
        sections = [SecSection(item_id="full", title="Full", text=doc.text)]

    section_budget = max(budget // max(len(sections), 1), 2_000)
    for section in sections:
        anchor = section.item_id in {"2", "7"}
        pulled.extend(
            select_paragraphs_from_section(
                section,
                doc.text,
                section_budget,
                anchor_first=anchor,
            )
        )

    unique_excerpts: list[str] = []
    seen: set[str] = set()
    used = 0
    for item in sorted(pulled, key=lambda row: (-row.score, len(row.text))):
        if item.text in seen:
            continue
        if item.text not in doc.text:
            continue
        extra = len(item.text) + (len(EXCERPT_SEPARATOR) if unique_excerpts else 0)
        if used + extra > budget:
            continue
        seen.add(item.text)
        unique_excerpts.append(item.text)
        used += extra

    if not unique_excerpts and doc.text.strip():
        unique_excerpts = [doc.text[:budget].strip()]

    return DocumentExcerptResult(
        doc_key=key,
        doc_type=doc.doc_type,
        quarter_label=doc.quarter_label,
        section_label=doc.section_label,
        raw_chars=raw_chars,
        excerpt_chars=sum(len(text) for text in unique_excerpts),
        excerpt_count=len(unique_excerpts),
        excerpts=unique_excerpts,
    )


def pull_excerpts(
    documents: list[LoadedDocument],
    *,
    primary_quarter: str,
    max_analysis_chars: int = DEFAULT_MAX_ANALYSIS_CHARS,
) -> ExcerptPullResult:
    budgets = _allocate_budgets(
        documents,
        max_analysis_chars=max_analysis_chars,
        primary_quarter=primary_quarter,
    )
    results: list[DocumentExcerptResult] = []
    for doc in documents:
        results.append(
            pull_excerpts_from_document(
                doc,
                budget=budgets[_doc_key(doc)],
                primary_quarter=primary_quarter,
            )
        )
    return ExcerptPullResult(
        documents=results,
        total_raw_chars=sum(item.raw_chars for item in results),
        total_excerpt_chars=sum(item.excerpt_chars for item in results),
        total_excerpt_count=sum(item.excerpt_count for item in results),
    )
