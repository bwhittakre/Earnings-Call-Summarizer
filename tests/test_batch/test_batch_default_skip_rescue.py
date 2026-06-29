import unittest
from unittest.mock import MagicMock, patch

from src.batch.historical_runner import run_historical_batch
from src.llm.quarter_summarizer import ValidatedQuarterOutput
from src.schemas.models import EvidenceClaim, QuarterSummary


def _fake_summary(quarter: str) -> QuarterSummary:
    claim = EvidenceClaim(claim="Revenue grew", excerpt="Revenue grew 10%")
    return QuarterSummary(
        company_name="Amazon",
        quarter=quarter,
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


class BatchDefaultSkipRescueTestCase(unittest.TestCase):
    @patch("src.batch.historical_runner.run_document_pipeline_from_loaded")
    @patch("src.batch.historical_runner.load_quarter_documents")
    @patch("src.batch.historical_runner._load_or_fetch_bundle")
    def test_batch_defaults_skip_rescue_judge(
        self,
        mock_load,
        mock_load_docs,
        mock_pipeline,
    ):
        bundle = MagicMock()
        bundle.knowledge_cutoff = None
        bundle.cache_dir = __import__("pathlib").Path("data/documents/amzn/2020-Q1")
        mock_load.return_value = bundle
        mock_load_docs.return_value = MagicMock()
        mock_pipeline.return_value = _fake_output("2020-Q1")

        run_historical_batch(
            MagicMock(),
            ticker="AMZN",
            quarter_count=1,
            end_quarter="2020-Q1",
        )

        _, kwargs = mock_pipeline.call_args
        self.assertTrue(kwargs["skip_rescue_judge"])

    @patch("src.batch.historical_runner.run_document_pipeline_from_loaded")
    @patch("src.batch.historical_runner.load_quarter_documents")
    @patch("src.batch.historical_runner._load_or_fetch_bundle")
    def test_batch_can_enable_rescue_judge(
        self,
        mock_load,
        mock_load_docs,
        mock_pipeline,
    ):
        bundle = MagicMock()
        bundle.knowledge_cutoff = None
        bundle.cache_dir = __import__("pathlib").Path("data/documents/amzn/2020-Q1")
        mock_load.return_value = bundle
        mock_load_docs.return_value = MagicMock()
        mock_pipeline.return_value = _fake_output("2020-Q1")

        run_historical_batch(
            MagicMock(),
            ticker="AMZN",
            quarter_count=1,
            end_quarter="2020-Q1",
            skip_rescue_judge=False,
        )

        _, kwargs = mock_pipeline.call_args
        self.assertFalse(kwargs["skip_rescue_judge"])


if __name__ == "__main__":
    unittest.main()
