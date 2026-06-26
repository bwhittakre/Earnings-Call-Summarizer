import unittest
from datetime import date
from pathlib import Path

from src.ingest.loader import TranscriptFile
from src.market.pipeline import build_market_context, resolve_call_date_value
from src.market.quarter_labels import prior_quarter_labels

AMAZON_OPENING = (
    "Hello, and welcome to our Q4 2025 financial results conference call. "
    "Our comments reflect management's views as of today, February 5, 2026, only."
)


class MarketPipelineTestCase(unittest.TestCase):
    def test_amazon_uses_reported_quarter_not_filename(self):
        call_date = resolve_call_date_value(AMAZON_OPENING)
        self.assertEqual(call_date, date(2026, 2, 5))
        self.assertEqual(
            prior_quarter_labels("2025-Q4"),
            ["2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3"],
        )

        def fake_fetcher(ticker: str, start: date, end: date):
            return [(end, 100.0 + end.day)]

        transcript_file = TranscriptFile(
            path=Path("FY2026-Q4.txt"),
            quarter="FY2026-Q4",
            quarter_from_filename=True,
        )
        context = build_market_context(
            ticker="AMZN",
            transcript_text=AMAZON_OPENING,
            call_date=call_date,
            reported_quarter="2025-Q4",
            transcript_file=transcript_file,
            fetcher=fake_fetcher,
        )
        self.assertEqual(context.reported_quarter, "2025-Q4")
        self.assertEqual(
            [price.quarter_label for price in context.prices],
            ["2024-Q4", "2025-Q1", "2025-Q2", "2025-Q3"],
        )
        for price in context.prices:
            self.assertLessEqual(price.price_date, call_date)
        self.assertIn("Reported quarter (from transcript): 2025-Q4", context.price_block_text)
        self.assertIn("Call date: (02,05,2026)", context.price_block_text)

    def test_amazon_transcript_file_integration(self):
        transcript_path = (
            Path(__file__).resolve().parent.parent
            / "data"
            / "transcripts"
            / "amazon"
            / "FY2026-Q4.txt"
        )
        if not transcript_path.exists():
            self.skipTest("Amazon FY2026-Q4 transcript fixture not present")

        text = transcript_path.read_text(encoding="utf-8", errors="replace")
        call_date = resolve_call_date_value(text)
        self.assertEqual(call_date, date(2026, 2, 5))

        def fake_fetcher(ticker: str, start: date, end: date):
            return [(end, 200.0)]

        context = build_market_context(
            ticker="AMZN",
            transcript_text=text,
            call_date=call_date,
            reported_quarter="2025-Q4",
            transcript_file=TranscriptFile(
                path=transcript_path,
                quarter="FY2026-Q4",
                quarter_from_filename=True,
            ),
            fetcher=fake_fetcher,
        )
        self.assertNotIn("FY2026-Q3", context.price_block_text)
        self.assertIn("2025-Q3", context.price_block_text)


if __name__ == "__main__":
    unittest.main()
