import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

from src.ingest.documents.fetch.filings_cache import get_ticker_filings, load_filings_cache
from src.ingest.documents.fetch.edgar_submissions import FilingRecord
from src.ingest.documents.models import DocumentType, FetchedDocument, FetchRequest, QuarterDocumentBundle
from src.ingest.documents.orchestrator import fetch_quarter_documents


class FilingsCacheTestCase(unittest.TestCase):
    def test_get_ticker_filings_uses_disk_cache(self):
        sample = [
            FilingRecord(
                form="8-K",
                accession_number="0001045810-24-000123",
                filing_date=date(2024, 8, 28),
                report_date=date(2024, 7, 28),
                primary_document="form8k.htm",
                items="2.02",
            )
        ]
        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            client = MagicMock()
            filings = get_ticker_filings(client, "0001045810", folder)
            self.assertEqual(len(filings), 0)
            client.get_json.assert_called()

            with patch(
                "src.ingest.documents.fetch.filings_cache.load_all_filings",
                return_value=sample,
            ):
                filings = get_ticker_filings(client, "0001045810", folder, force_refresh=True)
            self.assertEqual(len(filings), 1)

            cached = load_filings_cache(folder)
            self.assertIsNotNone(cached)
            self.assertEqual(cached[0].accession_number, sample[0].accession_number)

            client.get_json.reset_mock()
            with patch(
                "src.ingest.documents.fetch.filings_cache.load_all_filings",
                return_value=sample,
            ) as mock_load:
                cached_again = get_ticker_filings(client, "0001045810", folder)
            self.assertEqual(len(cached_again), 1)
            mock_load.assert_not_called()
            client.get_json.assert_not_called()


class TrimAtReadTestCase(unittest.TestCase):
    def test_trim_on_cached_bundle_avoids_refetch(self):
        with TemporaryDirectory() as tmp:
            folder = Path(tmp) / "nvda"
            quarter_dir = folder / "FY2025-Q2"
            quarter_dir.mkdir(parents=True)
            bundle = QuarterDocumentBundle(
                ticker="NVDA",
                quarter_label="FY2025-Q2",
                cache_dir=quarter_dir,
                corpus_trimmed=False,
                documents=[
                    FetchedDocument(
                        doc_type=DocumentType.PRESS_RELEASE,
                        text="Press release " + ("detail " * 5000),
                        filing_date=date(2024, 8, 28),
                    )
                ],
            )
            from src.ingest.documents.cache import load_bundle_from_cache, save_bundle

            save_bundle(bundle)
            loaded_bundle = load_bundle_from_cache(
                "NVDA",
                "FY2025-Q2",
                ticker_folder=folder,
            )
            self.assertIsNotNone(loaded_bundle)

            with (
                patch("src.ingest.documents.orchestrator.bundle_is_cached", return_value=True),
                patch(
                    "src.ingest.documents.orchestrator.load_bundle_from_cache",
                    return_value=loaded_bundle,
                ),
                patch("src.ingest.documents.orchestrator.allocate_quarter") as mock_alloc,
                patch(
                    "src.ingest.documents.orchestrator.trim_document_text",
                    side_effect=lambda doc: doc.text[:500],
                ),
            ):
                mock_alloc.side_effect = AssertionError("should not refetch when cache can be trimmed")
                result = fetch_quarter_documents(
                    FetchRequest(ticker="NVDA", quarter_label="FY2025-Q2", trim_corpus=True),
                    ticker_folder=folder,
                )
            self.assertTrue(result.corpus_trimmed)
            self.assertLessEqual(len(result.documents[0].text), 500)


if __name__ == "__main__":
    unittest.main()
