import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from src.ingest.documents.cache import load_bundle_from_cache, save_bundle
from src.ingest.documents.fetch.edgar_8k import _classify_exhibit
from src.ingest.documents.fetch.edgar_submissions import find_filings, iter_recent_filings
from src.ingest.documents.models import DocumentType, FetchedDocument, QuarterDocumentBundle


SAMPLE_SUBMISSIONS = {
    "filings": {
        "recent": {
            "form": ["8-K", "10-Q", "10-K"],
            "accessionNumber": [
                "0001045810-24-000123",
                "0001045810-24-000200",
                "0001045810-24-000300",
            ],
            "filingDate": ["2024-08-28", "2024-08-30", "2024-03-01"],
            "reportDate": ["2024-07-28", "2024-07-28", "2024-01-28"],
            "primaryDocument": ["form8k.htm", "form10q.htm", "form10k.htm"],
            "items": ["2.02", None, None],
        }
    }
}


class EdgarParsingTestCase(unittest.TestCase):
    def test_find_item_202_8k(self):
        filings = iter_recent_filings(SAMPLE_SUBMISSIONS)
        matches = find_filings(
            filings,
            form="8-K",
            start=date(2024, 7, 28),
            end=date(2024, 10, 1),
            item_contains="2.02",
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].accession_number, "0001045810-24-000123")

    def test_filed_on_or_before_excludes_future_filings(self):
        filings = iter_recent_filings(SAMPLE_SUBMISSIONS)
        matches = find_filings(
            filings,
            form="10-Q",
            filed_on_or_before=date(2024, 8, 30),
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].accession_number, "0001045810-24-000200")

        excluded = find_filings(
            filings,
            form="10-Q",
            filed_on_or_before=date(2024, 8, 29),
        )
        self.assertEqual(excluded, [])

    def test_classify_exhibit_press_release(self):
        self.assertEqual(
            _classify_exhibit("Press Release dated August 28, 2024", "ex99-1.htm"),
            "press_release",
        )

    def test_classify_exhibit_presentation(self):
        self.assertEqual(
            _classify_exhibit("Investor Presentation", "ex99-3.htm"),
            "presentation",
        )

    def test_cache_round_trip(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ticker_folder = root / "nvda"
            bundle = QuarterDocumentBundle(
                ticker="NVDA",
                quarter_label="FY2025-Q2",
                cache_dir=ticker_folder / "FY2025-Q2",
                documents=[
                    FetchedDocument(
                        doc_type=DocumentType.PRESS_RELEASE,
                        text="Press release announced record revenue for the quarter.",
                        accession_number="0001045810-24-000123",
                        filing_date=date(2024, 8, 28),
                    )
                ],
            )
            save_bundle(bundle)
            loaded = load_bundle_from_cache(
                "NVDA",
                "FY2025-Q2",
                ticker_folder=ticker_folder,
            )
            self.assertIsNotNone(loaded)
            assert loaded is not None
            self.assertEqual(len(loaded.documents), 1)
            manifest = json.loads((ticker_folder / "FY2025-Q2" / "manifest.json").read_text())
            self.assertEqual(manifest["ticker"], "NVDA")

    def test_manifest_persists_knowledge_cutoff(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            ticker_folder = root / "amzn"
            bundle = QuarterDocumentBundle(
                ticker="AMZN",
                quarter_label="2025-Q3",
                cache_dir=ticker_folder / "2025-Q3",
                knowledge_cutoff=date(2025, 10, 30),
                corpus_trimmed=True,
                documents=[
                    FetchedDocument(
                        doc_type=DocumentType.EIGHT_K,
                        text="Eight-K body",
                        filing_date=date(2025, 10, 30),
                    )
                ],
            )
            save_bundle(bundle)
            loaded = load_bundle_from_cache(
                "AMZN",
                "2025-Q3",
                ticker_folder=ticker_folder,
            )
            assert loaded is not None
            self.assertEqual(loaded.knowledge_cutoff, date(2025, 10, 30))
            self.assertTrue(loaded.corpus_trimmed)


if __name__ == "__main__":
    unittest.main()
