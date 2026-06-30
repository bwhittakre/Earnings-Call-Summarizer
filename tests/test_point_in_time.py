import unittest
from datetime import date
from unittest.mock import MagicMock, patch

from src.ingest.loader import LoadedTranscripts, TranscriptFile
from src.llm.quarter_summarizer import format_knowledge_cutoff_header
from src.market.stock_prices import StockPriceError, validate_prices_point_in_time
from src.market.models import QuarterEndPrice
from src.pipeline.point_in_time import PointInTimeConfig, PointInTimeError
from src.pipeline.runner import run_pipeline_from_loaded
from src.pipeline.strict_anchoring import resolve_strict_anchoring
from src.schemas.models import (
    EvidenceBackedQuarterSummary,
    EvidenceClaim,
    LLMResult,
    TokenUsage,
)

AMAZON_OPENING = (
    "Hello, and welcome to our Q4 2025 financial results conference call. "
    "Our comments reflect management's views as of today, February 5, 2026, only."
)


class PointInTimeTestCase(unittest.TestCase):
    def test_strict_quarter_mismatch_fails(self):
        with self.assertRaises(PointInTimeError) as ctx:
            resolve_strict_anchoring(
                transcript_text=AMAZON_OPENING,
                filename_quarter="FY2026-Q4",
                point_in_time=PointInTimeConfig.transcript_only(),
            )
        self.assertIn("does not match", str(ctx.exception))

    def test_strict_missing_call_date_fails(self):
        with self.assertRaises(PointInTimeError) as ctx:
            resolve_strict_anchoring(
                transcript_text="Welcome to our earnings call for Q1 2025.",
                filename_quarter="2025-Q1",
                point_in_time=PointInTimeConfig.transcript_only(),
            )
        self.assertIn("call date", str(ctx.exception).lower())

    def test_strict_rejects_reported_quarter_override(self):
        with self.assertRaises(PointInTimeError):
            resolve_strict_anchoring(
                transcript_text=AMAZON_OPENING,
                filename_quarter="2025-Q4",
                point_in_time=PointInTimeConfig.transcript_only(),
                reported_quarter_override="2025-Q3",
            )

    def test_strict_matching_quarter_succeeds(self):
        call_date, reported = resolve_strict_anchoring(
            transcript_text=AMAZON_OPENING,
            filename_quarter="2025-Q4",
            point_in_time=PointInTimeConfig.transcript_only(),
        )
        self.assertEqual(call_date, date(2026, 2, 5))
        self.assertEqual(reported, "2025-Q4")

    def test_validate_prices_rejects_future_price_date(self):
        prices = [
            QuarterEndPrice(
                quarter_label="2025-Q3",
                quarter_end_date=date(2025, 9, 30),
                price_date=date(2026, 2, 6),
                adjusted_close=100.0,
                ticker="AMZN",
            )
        ]
        with self.assertRaises(StockPriceError):
            validate_prices_point_in_time(prices, date(2026, 2, 5))

    @patch("src.pipeline.runner.QuarterSummarizer")
    def test_point_in_time_disables_ticker_path(self, summarizer_cls):
        from src.llm.quarter_summarizer import ValidatedQuarterOutput
        from src.schemas.models import QuarterSummary

        evidence = EvidenceBackedQuarterSummary(
            company_name="Amazon",
            quarter="2025-Q4",
            what_happened=[
                EvidenceClaim(
                    claim="Results",
                    excerpt="Hello, and welcome to our Q4 2025 financial results conference call.",
                )
            ],
            positives=[],
            negatives=[],
            confidence_score=10,
            analysis=[
                EvidenceClaim(
                    claim="+10: Solid quarter",
                    excerpt="Hello, and welcome to our Q4 2025 financial results conference call.",
                )
            ],
        )
        summary = QuarterSummary(
            company_name="Amazon",
            quarter="2025-Q4",
            call_date="(02,05,2026)",
            what_happened=["Results"],
            positives=[],
            negatives=[],
            transcript_only_confidence_score=10,
            confidence_score=10,
            analysis=evidence.analysis,
        )
        mock_summarizer = MagicMock()
        mock_summarizer.summarize.return_value = (
            ValidatedQuarterOutput(summary=summary, evidence=evidence),
            LLMResult(usage=TokenUsage(input_tokens=1, output_tokens=1), raw_response="{}"),
        )
        summarizer_cls.return_value = mock_summarizer

        loaded = LoadedTranscripts(
            files=[
                TranscriptFile(
                    path=__import__("pathlib").Path("2025-Q4.txt"),
                    quarter="2025-Q4",
                    quarter_from_filename=True,
                )
            ],
            transcripts={"2025-Q4": AMAZON_OPENING},
        )

        with patch("src.pipeline.runner.build_market_context") as build_ctx:
            run_pipeline_from_loaded(
                MagicMock(),
                loaded,
                ticker="AMZN",
                point_in_time=PointInTimeConfig.transcript_only(),
            )
            build_ctx.assert_not_called()

        init_kwargs = summarizer_cls.call_args.kwargs
        self.assertTrue(init_kwargs["skip_rescue_judge"])
        self.assertTrue(init_kwargs["point_in_time"].active)

    def test_knowledge_cutoff_header_format(self):
        header = format_knowledge_cutoff_header(date(2026, 2, 5))
        self.assertIn("KNOWLEDGE CUTOFF: Treat (02,05,2026) as today.", header)
        self.assertIn("PRIOR QUARTER STOCK PRICES", header)


if __name__ == "__main__":
    unittest.main()
