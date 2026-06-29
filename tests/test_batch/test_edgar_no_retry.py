import unittest
from unittest.mock import MagicMock, patch

from src.batch.historical_runner import run_historical_batch
from src.ingest.documents.models import DocumentFetchError


class EdgarNoRetryTestCase(unittest.TestCase):
    @patch("src.batch.historical_runner._run_quarter_pipeline")
    @patch("src.batch.historical_runner._load_or_fetch_bundle")
    def test_edgar_fetch_error_not_retried(self, mock_load, mock_pipeline):
        mock_load.side_effect = DocumentFetchError("No earnings 8-K found")

        results = run_historical_batch(
            MagicMock(),
            ticker="AMZN",
            quarter_count=2,
            end_quarter="2020-Q2",
        )
        self.assertEqual(len(results), 2)
        self.assertTrue(all(item.status == "failed" for item in results))
        mock_pipeline.assert_not_called()


if __name__ == "__main__":
    unittest.main()
