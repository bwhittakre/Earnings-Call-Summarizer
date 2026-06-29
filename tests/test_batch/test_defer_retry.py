import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.batch.historical_runner import run_historical_batch
from src.batch.models import BatchQuarterResult
from src.llm.quarter_summarizer import ValidatedQuarterOutput
from src.schemas.models import EvidenceClaim, QuarterSummary


def _fake_summary(quarter: str) -> QuarterSummary:
    claim = EvidenceClaim(claim="Revenue grew", excerpt="Revenue grew 10%")
    return QuarterSummary(
        company_name="Amazon",
        quarter=quarter,
        call_date="2020-01-30",
        what_happened=["Revenue grew"],
        positives=["Strong AWS"],
        negatives=["Higher spend"],
        transcript_only_confidence_score=50,
        confidence_score=55,
        analysis=[claim],
    )


def _fake_output(quarter: str) -> ValidatedQuarterOutput:
    return ValidatedQuarterOutput(
        summary=_fake_summary(quarter),
        evidence=MagicMock(),
        backfilled_from_analysis=[],
    )


class DeferRetryTestCase(unittest.TestCase):
    @patch("src.batch.historical_runner._run_quarter_pipeline")
    @patch("src.batch.historical_runner._load_or_fetch_bundle")
    def test_retry_succeeds_on_second_pass(self, mock_load, mock_pipeline):
        bundle = MagicMock()
        bundle.knowledge_cutoff = date(2020, 1, 30)
        bundle.cache_dir = Path("data/documents/amzn/2020-Q1")
        mock_load.return_value = bundle

        mock_pipeline.side_effect = [
            RuntimeError("transient API error"),
            _fake_output("2020-Q1"),
        ]

        client = MagicMock()
        results = run_historical_batch(
            client,
            ticker="AMZN",
            quarter_count=1,
            end_quarter="2020-Q1",
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].status, "success")
        self.assertEqual(results[0].attempts, 2)
        self.assertEqual(mock_pipeline.call_count, 2)

    @patch("src.batch.historical_runner._run_quarter_pipeline")
    @patch("src.batch.historical_runner._load_or_fetch_bundle")
    def test_second_failure_marks_skipped(self, mock_load, mock_pipeline):
        bundle = MagicMock()
        bundle.knowledge_cutoff = date(2020, 4, 30)
        bundle.cache_dir = Path("data/documents/amzn/2020-Q2")
        mock_load.return_value = bundle
        mock_pipeline.side_effect = [
            RuntimeError("first failure"),
            RuntimeError("second failure"),
        ]

        results = run_historical_batch(
            MagicMock(),
            ticker="AMZN",
            quarter_count=1,
            end_quarter="2020-Q2",
        )
        self.assertEqual(results[0].status, "skipped")
        self.assertEqual(results[0].attempts, 2)
        self.assertIn("second failure", results[0].last_error or "")


if __name__ == "__main__":
    unittest.main()
