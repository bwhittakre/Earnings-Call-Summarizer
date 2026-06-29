import unittest
from datetime import date

from src.ingest.documents.allocation import allocate_quarter
from src.ingest.documents.corpus import build_document_corpus, corpus_section_labels
from src.ingest.documents.models import DocumentType, FetchedDocument, QuarterDocumentBundle
from src.schemas.models import EvidenceBackedQuarterSummary, EvidenceClaim
from src.validation.evidence_validator import validate_quarter_evidence


class AllocationTestCase(unittest.TestCase):
    def test_q2_allocation_expects_ten_q_not_primary_ten_k(self):
        allocation = allocate_quarter("NVDA", "FY2025-Q2")
        self.assertTrue(allocation.needs_ten_q)
        self.assertFalse(allocation.needs_ten_k_primary)
        self.assertTrue(allocation.needs_ten_k_context)

    def test_q4_allocation_expects_primary_ten_k(self):
        allocation = allocate_quarter("NVDA", "FY2025-Q4")
        self.assertFalse(allocation.needs_ten_q)
        self.assertTrue(allocation.needs_ten_k_primary)
        self.assertFalse(allocation.needs_ten_k_context)


class CorpusBuilderTestCase(unittest.TestCase):
    def test_build_document_corpus_orders_sections(self):
        bundle = QuarterDocumentBundle(
            ticker="NVDA",
            quarter_label="FY2025-Q2",
            cache_dir=__import__("pathlib").Path("."),
            documents=[
                FetchedDocument(
                    doc_type=DocumentType.TEN_Q,
                    text="Ten Q revenue grew strongly in the quarter.",
                ),
                FetchedDocument(
                    doc_type=DocumentType.PRESS_RELEASE,
                    text="Press release announced record revenue for the quarter.",
                ),
            ],
        )
        corpus = build_document_corpus(bundle)
        self.assertLess(
            corpus.index("--- EARNINGS PRESS RELEASE ---"),
            corpus.index("--- 10-Q ---"),
        )
        self.assertEqual(
            corpus_section_labels(bundle),
            ["EARNINGS PRESS RELEASE", "10-Q"],
        )


class CorpusValidationTestCase(unittest.TestCase):
    def test_excerpt_validates_against_combined_corpus(self):
        bundle = QuarterDocumentBundle(
            ticker="NVDA",
            quarter_label="FY2025-Q2",
            cache_dir=__import__("pathlib").Path("."),
            documents=[
                FetchedDocument(
                    doc_type=DocumentType.TEN_Q,
                    text="Ten Q revenue grew strongly in the quarter.",
                ),
                FetchedDocument(
                    doc_type=DocumentType.PRESS_RELEASE,
                    text="Press release announced record revenue for the quarter.",
                ),
            ],
        )
        corpus = build_document_corpus(bundle)
        evidence = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2025-Q2",
            what_happened=[
                EvidenceClaim(
                    claim="Ten Q growth",
                    excerpt="Ten Q revenue grew strongly in the quarter.",
                )
            ],
            positives=[],
            negatives=[],
            confidence_score=10,
            analysis=[
                EvidenceClaim(
                    claim="+10: Press release record revenue",
                    excerpt="Press release announced record revenue for the quarter.",
                )
            ],
        )
        result = validate_quarter_evidence(evidence, corpus)
        self.assertTrue(result.is_valid, result.error_message())


if __name__ == "__main__":
    unittest.main()
