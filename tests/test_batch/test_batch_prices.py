import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from src.batch.historical_runner import run_historical_batch
from src.ingest.documents.models import DocumentFetchError
from src.market.constants import BATCH_PRIOR_QUARTER_PRICE_COUNT
from src.market.pipeline import build_market_context
from src.ingest.loader import TranscriptFile


class BatchPriceCountTestCase(unittest.TestCase):
    @patch("src.market.pipeline.save_price_audit")
    @patch("src.market.pipeline.fetch_quarter_end_prices")
    def test_batch_runner_uses_six_prior_quarters(self, mock_fetch, _mock_audit):
        mock_fetch.return_value = []

        build_market_context(
            ticker="AMZN",
            transcript_text="Call Date: October 30, 2025",
            call_date=date(2025, 10, 30),
            reported_quarter="2025-Q3",
            transcript_file=TranscriptFile(
                path=Path(__file__),
                quarter="2025-Q3",
                quarter_from_filename=True,
            ),
            price_history_quarters=BATCH_PRIOR_QUARTER_PRICE_COUNT,
        )

        _, kwargs = mock_fetch.call_args
        self.assertEqual(kwargs["as_of_date"], date(2025, 10, 30))
        ordered_labels = kwargs["ordered_labels"]
        self.assertEqual(len(ordered_labels), 6)
        self.assertEqual(ordered_labels[-1], "2025-Q2")


class BatchRunnerPlaceholderTestCase(unittest.TestCase):
    @patch("src.batch.historical_runner.fetch_quarter_documents")
    def test_fetch_failure_yields_placeholder(self, mock_fetch):
        mock_fetch.side_effect = DocumentFetchError("missing 8-K")

        results = run_historical_batch(
            None,
            ticker="AMZN",
            years=1,
            end_quarter="2025-Q3",
            fetch=True,
            dry_run=True,
        )
        self.assertEqual(len(results), 4)
        self.assertTrue(all(item.status == "failed" for item in results))


if __name__ == "__main__":
    unittest.main()
