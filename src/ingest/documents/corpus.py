from __future__ import annotations

import re

from src.ingest.documents.models import DOCUMENT_FILENAMES, DocumentType, QuarterDocumentBundle

_CORPUS_SECTION_ORDER: tuple[DocumentType, ...] = (
    DocumentType.EIGHT_K,
    DocumentType.PRESS_RELEASE,
    DocumentType.INVESTOR_PRESENTATION,
    DocumentType.TEN_Q,
    DocumentType.TEN_K,
    DocumentType.TEN_K_CONTEXT,
)

_SECTION_TITLES: dict[DocumentType, str] = {
    DocumentType.EIGHT_K: "8-K",
    DocumentType.PRESS_RELEASE: "EARNINGS PRESS RELEASE",
    DocumentType.TEN_Q: "10-Q",
    DocumentType.TEN_K: "10-K",
    DocumentType.TEN_K_CONTEXT: "10-K (PRIOR ANNUAL CONTEXT)",
    DocumentType.INVESTOR_PRESENTATION: "INVESTOR PRESENTATION",
}

_POS_NEG_SECTION_KEYS = ("EARNINGS PRESS RELEASE", "8-K")
_SECTION_HEADER_PATTERN = re.compile(r"^---\s*(.+?)\s*---\s*$", re.MULTILINE)


def build_document_corpus(bundle: QuarterDocumentBundle) -> str:
    sections: list[str] = []
    by_type = {doc.doc_type: doc for doc in bundle.documents}

    for doc_type in _CORPUS_SECTION_ORDER:
        doc = by_type.get(doc_type)
        if not doc or not doc.text.strip():
            continue
        meta_parts = [_SECTION_TITLES[doc_type]]
        if doc.accession_number:
            meta_parts.append(f"accession {doc.accession_number}")
        if doc.filing_date:
            meta_parts.append(f"filed {doc.filing_date.isoformat()}")
        header = f"--- {'; '.join(meta_parts)} ---"
        sections.extend([header, doc.text.strip(), ""])

    if not sections:
        return ""
    return "\n".join(sections).strip()


def corpus_section_labels(bundle: QuarterDocumentBundle) -> list[str]:
    labels: list[str] = []
    by_type = {doc.doc_type: doc for doc in bundle.documents}
    for doc_type in _CORPUS_SECTION_ORDER:
        doc = by_type.get(doc_type)
        if doc and doc.text.strip():
            labels.append(_SECTION_TITLES[doc_type])
    return labels


def extract_corpus_sections(corpus_text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(_SECTION_HEADER_PATTERN.finditer(corpus_text))
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(corpus_text)
        body = corpus_text[start:end].strip()
        if body:
            sections[title] = body
    return sections


def pos_neg_validation_source(corpus_text: str) -> str:
    sections = extract_corpus_sections(corpus_text)
    parts = [sections[key] for key in _POS_NEG_SECTION_KEYS if key in sections]
    if parts:
        return "\n\n".join(parts)
    return corpus_text
