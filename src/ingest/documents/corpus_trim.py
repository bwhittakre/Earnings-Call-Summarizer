from __future__ import annotations

import re

from src.ingest.documents.models import DocumentType, FetchedDocument

_PERIODIC_DOC_MAX_CHARS = 40_000
_PRESENTATION_MAX_CHARS = 20_000

_SECTION_PATTERNS = (
    re.compile(r"item\s*2[\.\s].*management", re.IGNORECASE),
    re.compile(r"management['\u2019]?s discussion and analysis", re.IGNORECASE),
    re.compile(r"results of operations", re.IGNORECASE),
    re.compile(r"financial condition", re.IGNORECASE),
)


def _cap_text(text: str, limit: int) -> str:
    cleaned = text.strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "\n[... truncated for batch corpus ...]"


def extract_periodic_sections(text: str, limit: int = _PERIODIC_DOC_MAX_CHARS) -> str:
    lines = text.splitlines()
    chunks: list[str] = []
    capture = False
    current: list[str] = []

    for line in lines:
        if any(pattern.search(line) for pattern in _SECTION_PATTERNS):
            if current:
                chunks.append("\n".join(current))
            current = [line]
            capture = True
            continue
        if capture:
            if re.match(r"^\s*item\s+\d", line, re.IGNORECASE) and current:
                chunks.append("\n".join(current))
                current = []
                capture = False
                continue
            current.append(line)

    if current:
        chunks.append("\n".join(current))

    if chunks:
        merged = "\n\n".join(chunks)
        return _cap_text(merged, limit)
    return _cap_text(text, limit)


def trim_document_text(doc: FetchedDocument) -> str:
    if doc.doc_type in {DocumentType.TEN_Q, DocumentType.TEN_K, DocumentType.TEN_K_CONTEXT}:
        return extract_periodic_sections(doc.text)
    if doc.doc_type == DocumentType.INVESTOR_PRESENTATION:
        return _cap_text(doc.text, _PRESENTATION_MAX_CHARS)
    return doc.text
