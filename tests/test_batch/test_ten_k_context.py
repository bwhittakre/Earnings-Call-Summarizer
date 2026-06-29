import unittest
from datetime import date

from src.ingest.documents.allocation import QuarterAllocation
from src.ingest.documents.fetch.edgar_10k import fetch_ten_k_context
from src.ingest.documents.fetch.edgar_submissions import FilingRecord


class TenKContextCutoffTestCase(unittest.TestCase):
    def test_prior_annual_only_before_quarter_end(self):
        filings = [
            FilingRecord(
                form="10-K",
                accession_number="prior",
                filing_date=date(2024, 2, 1),
                report_date=date(2023, 12, 31),
                primary_document="10k.htm",
                items=None,
            ),
            FilingRecord(
                form="10-K",
                accession_number="same_quarter_annual",
                filing_date=date(2025, 10, 15),
                report_date=date(2025, 12, 31),
                primary_document="10k.htm",
                items=None,
            ),
        ]
        allocation = QuarterAllocation(
            quarter_label="2025-Q3",
            quarter_num=3,
            quarter_end=date(2025, 9, 30),
            earnings_window_start=date(2025, 10, 1),
            earnings_window_end=date(2025, 11, 15),
            needs_ten_q=True,
            needs_ten_k_primary=False,
            needs_ten_k_context=True,
        )

        class StubClient:
            def get_text(self, url: str) -> str:
                return "Annual report body"

        selected = fetch_ten_k_context(
            StubClient(),
            "0001018724",
            filings,
            allocation,
            knowledge_cutoff=date(2025, 10, 30),
        )
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.accession_number, "prior")


if __name__ == "__main__":
    unittest.main()
