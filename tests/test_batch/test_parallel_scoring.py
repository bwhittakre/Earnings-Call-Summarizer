import threading
import time
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


class ParallelScoringTestCase(unittest.TestCase):
    @patch("src.batch.historical_runner.batch_quarter_labels_for_ticker", return_value=["2020-Q1", "2020-Q2", "2020-Q3", "2020-Q4"])
    @patch("src.batch.historical_runner.run_document_pipeline_from_loaded")
    @patch("src.batch.historical_runner.bundle_to_loaded")
    @patch("src.batch.historical_runner._load_or_fetch_bundle")
    def test_parallel_workers_finish_faster_than_sequential(
        self,
        mock_load,
        mock_bundle_to_loaded,
        mock_pipeline,
        _mock_labels,
    ):
        def slow_pipeline(*args, **kwargs):
            time.sleep(0.15)
            loaded = kwargs.get("loaded") or args[1]
            quarter = loaded.quarter_label
            return _fake_output(quarter)

        mock_pipeline.side_effect = slow_pipeline

        def make_bundle(quarter: str):
            bundle = MagicMock()
            bundle.knowledge_cutoff = None
            bundle.cache_dir = __import__("pathlib").Path(f"data/documents/amzn/{quarter}")
            return bundle

        quarters = [f"2020-Q{i}" for i in range(1, 5)]

        def loaded_side_effect(bundle, *, ticker=None):
            loaded = MagicMock()
            loaded.quarter_label = getattr(bundle, "_test_quarter", "2020-Q1")
            loaded.bundle = bundle
            return loaded

        def bundle_side_effect(**kwargs):
            quarter = kwargs["quarter_label"]
            bundle = make_bundle(quarter)
            bundle._test_quarter = quarter
            return bundle

        mock_load.side_effect = bundle_side_effect
        mock_bundle_to_loaded.side_effect = loaded_side_effect

        start_seq = time.monotonic()
        run_historical_batch(
            MagicMock(),
            ticker="AMZN",
            quarter_count=4,
            end_quarter="2020-Q4",
            batch_workers=1,
        )
        sequential_elapsed = time.monotonic() - start_seq

        mock_pipeline.reset_mock()
        start_par = time.monotonic()
        results = run_historical_batch(
            MagicMock(),
            ticker="AMZN",
            quarter_count=4,
            end_quarter="2020-Q4",
            batch_workers=4,
        )
        parallel_elapsed = time.monotonic() - start_par

        self.assertEqual(len(results), 4)
        self.assertLess(parallel_elapsed, sequential_elapsed * 0.85)
        self.assertEqual(mock_pipeline.call_count, 4)


class BatchWorkersOneTestCase(unittest.TestCase):
    @patch("src.batch.historical_runner.run_document_pipeline_from_loaded")
    @patch("src.batch.historical_runner.bundle_to_loaded")
    @patch("src.batch.historical_runner._load_or_fetch_bundle")
    def test_batch_workers_one_runs_sequential(
        self,
        mock_load,
        mock_bundle_to_loaded,
        mock_pipeline,
    ):
        bundle = MagicMock()
        bundle.knowledge_cutoff = None
        bundle.cache_dir = __import__("pathlib").Path("data/documents/amzn/2020-Q1")
        mock_load.return_value = bundle
        loaded = MagicMock()
        loaded.quarter_label = "2020-Q1"
        loaded.bundle = bundle
        mock_bundle_to_loaded.return_value = loaded
        mock_pipeline.return_value = _fake_output("2020-Q1")

        run_historical_batch(
            MagicMock(),
            ticker="AMZN",
            quarter_count=1,
            end_quarter="2020-Q1",
            batch_workers=1,
        )
        self.assertEqual(mock_pipeline.call_count, 1)


if __name__ == "__main__":
    unittest.main()
