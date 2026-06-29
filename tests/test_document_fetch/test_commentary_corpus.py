import unittest
from datetime import date
from pathlib import Path

from src.ingest.documents.corpus import (
    build_document_corpus,
    corpus_section_labels,
    pos_neg_validation_source,
)
from src.ingest.documents.models import DocumentType, FetchedDocument, QuarterDocumentBundle


class CommentaryCorpusTestCase(unittest.TestCase):
    def _bundle(self) -> QuarterDocumentBundle:
        return QuarterDocumentBundle(
            ticker="NVDA",
            quarter_label="FY2025-Q2",
            cache_dir=Path("test_cache"),
            documents=[
                FetchedDocument(
                    doc_type=DocumentType.EIGHT_K,
                    text="Item 2.02 results of operations.",
                    filing_date=date(2024, 8, 28),
                ),
                FetchedDocument(
                    doc_type=DocumentType.PRESS_RELEASE,
                    text="NVIDIA announced record revenue.",
                    filing_date=date(2024, 8, 28),
                ),
                FetchedDocument(
                    doc_type=DocumentType.CFO_COMMENTARY,
                    text="Data center revenue was $26.3 billion.",
                    filing_date=date(2024, 8, 28),
                ),
            ],
        )

    def test_commentary_in_corpus_order(self):
        bundle = self._bundle()
        corpus = build_document_corpus(bundle)
        self.assertIn("--- CFO COMMENTARY", corpus)
        pr_index = corpus.index("EARNINGS PRESS RELEASE")
        commentary_index = corpus.index("CFO COMMENTARY")
        ten_q_placeholder = corpus.find("10-Q")
        self.assertLess(pr_index, commentary_index)
        self.assertIn("Data center revenue was $26.3 billion.", corpus)

    def test_commentary_in_section_labels(self):
        labels = corpus_section_labels(self._bundle())
        self.assertIn("CFO COMMENTARY", labels)

    def test_pos_neg_validation_includes_commentary(self):
        corpus = build_document_corpus(self._bundle())
        source = pos_neg_validation_source(corpus)
        self.assertIn("record revenue", source)
        self.assertIn("Data center revenue was $26.3 billion.", source)


if __name__ == "__main__":
    unittest.main()
