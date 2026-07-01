import unittest
from datetime import date
from pathlib import Path

from src.market.pipeline import build_market_context
from src.market.quarter_labels import prior_quarter_labels

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "filings"


class MarketPipelineTestCase(unittest.TestCase):
    def test_build_market_context_uses_as_of_date_and_reported_quarter(self):
        as_of_date = date(2026, 2, 5)
        self.assertEqual(
            prior_quarter_labels("2025-Q4"),
            ["2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3"],
        )

        def fake_fetcher(ticker: str, start: date, end: date):
            return [(end, 100.0 + end.day)]

        context = build_market_context(
            ticker="AMZN",
            as_of_date=as_of_date,
            reported_quarter="2025-Q4",
            audit_label="AMZN_2025-Q4",
            fetcher=fake_fetcher,
        )
        self.assertEqual(context.reported_quarter, "2025-Q4")
        self.assertEqual(
            [price.quarter_label for price in context.prices],
            ["2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3"],
        )
        for price in context.prices:
            self.assertLessEqual(price.price_date, as_of_date)
        self.assertIn("Reported quarter (from filing package): 2025-Q4", context.price_block_text)
        self.assertIn("As-of date: (02,05,2026)", context.price_block_text)

    def test_filing_fixture_as_of_date(self):
        from src.ingest.filings import load_filing_packages

        packages = load_filing_packages(
            FIXTURES_ROOT,
            companies="AMZN",
            quarter="2025-Q4",
        )
        package = packages[0]
        self.assertEqual(package.as_of_date, date(2026, 2, 5))
        self.assertIn("Q4 2025 financial results", package.corpus_text)


if __name__ == "__main__":
    unittest.main()
