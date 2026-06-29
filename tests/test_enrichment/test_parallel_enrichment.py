import unittest
from unittest.mock import MagicMock, patch

from src.enrichment.enrichment_runner import run_batch_enrichment
from src.enrichment.models import EnrichmentResult


class ParallelEnrichmentTestCase(unittest.TestCase):
    @patch("src.enrichment.enrichment_runner.run_quarter_enrichment")
    def test_enrichment_workers_parallel(self, mock_run):
        mock_run.side_effect = [
            EnrichmentResult(quarter=f"2024-Q{i}", availability="found", notes="ok")
            for i in range(1, 5)
        ]
        results = run_batch_enrichment(
            MagicMock(),
            ticker="AMZN",
            quarter_labels=[f"2024-Q{i}" for i in range(1, 5)],
            enrichment_workers=4,
        )
        self.assertEqual(len(results), 4)
        self.assertEqual(mock_run.call_count, 4)
        self.assertEqual(results[0].quarter, "2024-Q1")
        self.assertEqual(results[-1].quarter, "2024-Q4")


if __name__ == "__main__":
    unittest.main()
