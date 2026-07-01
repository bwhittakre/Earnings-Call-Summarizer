from __future__ import annotations

from dataclasses import dataclass

from src.ingest.filings.corpus import section_tag
from src.ingest.filings.excerpt_puller import EXCERPT_SEPARATOR, DocumentExcerptResult
from src.ingest.filings.types import LoadedDocument


@dataclass
class ExcerptStats:
    raw_corpus_chars: int
    analysis_corpus_chars: int
    excerpt_count: int
    per_document: list[dict[str, int | str]]

    def to_dict(self) -> dict:
        return {
            "raw_corpus_chars": self.raw_corpus_chars,
            "analysis_corpus_chars": self.analysis_corpus_chars,
            "excerpt_count": self.excerpt_count,
            "per_document": self.per_document,
        }


def build_analysis_corpus_from_results(
    results: list[DocumentExcerptResult],
) -> str:
    sections: list[str] = []
    for result in results:
        if not result.excerpts:
            continue
        tag = section_tag(
            result.doc_type,
            result.quarter_label,
            result.section_label,
        )
        sections.append(f"=== {tag} ===")
        sections.append(EXCERPT_SEPARATOR.join(result.excerpts))
        sections.append("")
    return "\n".join(sections).strip()


def build_analysis_corpus(
    documents: list[LoadedDocument],
    results: list[DocumentExcerptResult],
) -> tuple[str, ExcerptStats]:
    corpus = build_analysis_corpus_from_results(results)
    per_document = [
        {
            "doc_key": result.doc_key,
            "raw_chars": result.raw_chars,
            "excerpt_chars": result.excerpt_chars,
            "excerpt_count": result.excerpt_count,
        }
        for result in results
    ]
    stats = ExcerptStats(
        raw_corpus_chars=sum(len(doc.text) for doc in documents),
        analysis_corpus_chars=len(corpus),
        excerpt_count=sum(result.excerpt_count for result in results),
        per_document=per_document,
    )
    return corpus, stats
