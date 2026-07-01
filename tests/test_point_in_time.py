import unittest
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.ingest.filings import load_filing_packages
from src.llm.quarter_summarizer import format_knowledge_cutoff_header
from src.market.stock_prices import StockPriceError, validate_prices_point_in_time
from src.market.models import QuarterEndPrice
from src.pipeline.point_in_time import PointInTimeConfig
from src.pipeline.runner import run_pipeline_from_packages
from src.schemas.models import (
    EvidenceBackedQuarterSummary,
    EvidenceClaim,
    LLMResult,
    TokenUsage,
)

FIXTURES_ROOT = Path(__file__).parent / "fixtures" / "filings"


class PointInTimeTestCase(unittest.TestCase):
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
            as_of_date="(02,05,2026)",
            what_happened=["Results"],
            positives=[],
            negatives=[],
            document_only_confidence_score=10,
            confidence_score=10,
            analysis=evidence.analysis,
        )
        mock_summarizer = MagicMock()
        mock_summarizer.summarize.return_value = (
            ValidatedQuarterOutput(summary=summary, evidence=evidence),
            LLMResult(usage=TokenUsage(input_tokens=1, output_tokens=1), raw_response="{}"),
        )
        summarizer_cls.return_value = mock_summarizer

        packages = load_filing_packages(
            FIXTURES_ROOT,
            companies="AMZN",
            quarter="2025-Q4",
            require_as_of_date=True,
        )

        with patch("src.pipeline.runner.build_market_context") as build_ctx:
            run_pipeline_from_packages(
                MagicMock(),
                packages,
                ticker="AMZN",
                point_in_time=PointInTimeConfig.document_only(),
            )
            build_ctx.assert_not_called()

        init_kwargs = summarizer_cls.call_args.kwargs
        self.assertTrue(init_kwargs["skip_rescue_judge"])
        self.assertTrue(init_kwargs["point_in_time"].active)

        summarize_kwargs = mock_summarizer.summarize.call_args.kwargs
        self.assertIn("corpus_text", summarize_kwargs)
        self.assertEqual(summarize_kwargs["as_of_date"], date(2026, 2, 5))

    def test_knowledge_cutoff_header_format(self):
        header = format_knowledge_cutoff_header(date(2026, 2, 5))
        self.assertIn("KNOWLEDGE CUTOFF: Treat (02,05,2026) as today.", header)
        self.assertIn("PRIOR QUARTER STOCK PRICES", header)
        self.assertIn("filing corpus", header)


if __name__ == "__main__":
    unittest.main()
