from __future__ import annotations

from src.enrichment.transcript_cache import read_cached_transcript
from src.ingest.documents.models import DocumentType, QuarterDocumentBundle

_FETCH_SUMMARY_LABELS: dict[DocumentType, str] = {
    DocumentType.EIGHT_K: "8-K",
    DocumentType.PRESS_RELEASE: "PR",
    DocumentType.CFO_COMMENTARY: "Commentary",
    DocumentType.TEN_Q: "10-Q",
    DocumentType.TEN_K: "10-K",
    DocumentType.TEN_K_CONTEXT: "10-K ctx",
    DocumentType.INVESTOR_PRESENTATION: "Presentation",
}

_EXPECTED_DOC_TYPES: tuple[DocumentType, ...] = (
    DocumentType.EIGHT_K,
    DocumentType.PRESS_RELEASE,
    DocumentType.CFO_COMMENTARY,
    DocumentType.TEN_Q,
    DocumentType.TEN_K,
    DocumentType.TEN_K_CONTEXT,
    DocumentType.INVESTOR_PRESENTATION,
)


def docs_present_by_type(bundle: QuarterDocumentBundle) -> dict[DocumentType, bool]:
    present: dict[DocumentType, bool] = {doc_type: False for doc_type in _EXPECTED_DOC_TYPES}
    for doc in bundle.documents:
        if doc.text.strip():
            present[doc.doc_type] = True
    return present


def transcript_available(ticker: str, quarter_label: str) -> bool:
    cached = read_cached_transcript(ticker, quarter_label)
    if cached and cached[0].strip():
        return True
    return False


def build_fetch_summary(
    bundle: QuarterDocumentBundle,
    *,
    ticker: str | None = None,
    transcript_found: bool | None = None,
) -> str:
    present = docs_present_by_type(bundle)
    found = [
        _FETCH_SUMMARY_LABELS[doc_type]
        for doc_type in _EXPECTED_DOC_TYPES
        if present[doc_type]
    ]
    parts = [" + ".join(found) if found else "none"]
    if ticker is not None:
        if transcript_found is None:
            transcript_found = transcript_available(ticker, bundle.quarter_label)
        parts.append(f"Transcript({'found' if transcript_found else 'missing'})")
    if bundle.corpus_trimmed:
        parts.append("trimmed")
    return "; ".join(parts)
