import unittest
from unittest.mock import MagicMock

from src.llm.quarter_summarizer import QuarterSummarizer
from src.schemas.models import (
    EvidenceBackedQuarterSummary,
    EvidenceClaim,
    LLMResult,
    PriceAnalysisBullets,
    TokenUsage,
)

CORPUS = (
    "=== 10-Q (FY2025-Q2) ===\n"
    "We saw strong demand in data center and raised our full-year outlook. "
    "Margins expanded due to mix. FX remained a headwind."
)


class QuarterSummarizerTestCase(unittest.TestCase):
    def test_preserves_llm_detected_company_name(self):
        evidence = EvidenceBackedQuarterSummary(
            company_name="Amazon",
            quarter="FY2025-Q2",
            what_happened=[
                EvidenceClaim(
                    claim="Strong demand",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                )
            ],
            positives=[],
            negatives=[],
            confidence_score=20,
            analysis=[
                EvidenceClaim(
                    claim="+20: Raised outlook supports next-quarter momentum",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                )
            ],
        )
        client = MagicMock()
        client.complete_json.return_value = (
            evidence,
            LLMResult(usage=TokenUsage(input_tokens=10, output_tokens=5), raw_response="{}"),
        )

        summarizer = QuarterSummarizer(client, skip_rescue_judge=False)
        output, _ = summarizer.summarize(
            quarter="FY2025-Q2",
            corpus_text=CORPUS,
            label="FY2025-Q2_quarter",
        )

        self.assertEqual(output.summary.company_name, "Amazon")
        self.assertEqual(output.evidence.company_name, "Amazon")

    def test_includes_price_block_in_user_content(self):
        filing_evidence = EvidenceBackedQuarterSummary(
            company_name="Amazon",
            quarter="FY2025-Q2",
            what_happened=[
                EvidenceClaim(
                    claim="Strong demand",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                )
            ],
            positives=[],
            negatives=[],
            confidence_score=20,
            analysis=[
                EvidenceClaim(
                    claim="+20: Raised outlook supports next-quarter momentum",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                )
            ],
        )
        price_evidence = PriceAnalysisBullets(
            analysis=[
                EvidenceClaim(
                    claim="+10: [price] Upward momentum",
                    excerpt="FY2024-Q3 end (2024-09-30, traded 2024-09-30): $186.00",
                )
            ]
        )
        client = MagicMock()
        client.complete_json.side_effect = [
            (
                filing_evidence,
                LLMResult(usage=TokenUsage(input_tokens=10, output_tokens=5), raw_response="{}"),
            ),
            (
                price_evidence,
                LLMResult(usage=TokenUsage(input_tokens=4, output_tokens=2), raw_response="{}"),
            ),
        ]

        price_block = (
            "--- PRIOR QUARTER STOCK PRICES (source: yfinance adjusted close; not from filings) ---\n"
            "Ticker: AMZN\n"
            "FY2024-Q3 end (2024-09-30, traded 2024-09-30): $186.00"
        )
        summarizer = QuarterSummarizer(client, skip_rescue_judge=True)
        output, _ = summarizer.summarize(
            quarter="FY2025-Q2",
            corpus_text=CORPUS,
            label="FY2025-Q2_quarter",
            price_block_text=price_block,
        )

        document_call = client.complete_json.call_args_list[0].kwargs
        price_call = client.complete_json.call_args_list[1].kwargs
        self.assertNotIn("PRIOR QUARTER STOCK PRICES", document_call["user_content"])
        self.assertIn("--- FILINGS ---", document_call["user_content"])
        self.assertIn("PRIOR QUARTER STOCK PRICES", price_call["user_content"])
        self.assertNotIn("--- FILINGS ---", price_call["user_content"])
        self.assertEqual(output.summary.document_only_confidence_score, 20)
        self.assertEqual(output.summary.confidence_score, 30)

    def test_injects_knowledge_cutoff_header_in_point_in_time_mode(self):
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
        client = MagicMock()
        client.complete_json.return_value = (
            evidence,
            LLMResult(usage=TokenUsage(input_tokens=10, output_tokens=5), raw_response="{}"),
        )

        from datetime import date

        from src.pipeline.point_in_time import PointInTimeConfig

        corpus = (
            "=== 10-Q (2025-Q4) ===\n"
            "Hello, and welcome to our Q4 2025 financial results conference call. "
            "Our comments reflect management's views as of today, February 5, 2026, only."
        )
        summarizer = QuarterSummarizer(
            client,
            skip_rescue_judge=True,
            point_in_time=PointInTimeConfig.document_only(),
        )
        summarizer.summarize(
            quarter="2025-Q4",
            corpus_text=corpus,
            label="2025-Q4_quarter",
            as_of_date=date(2026, 2, 5),
        )

        user_content = client.complete_json.call_args.kwargs["user_content"]
        self.assertIn("KNOWLEDGE CUTOFF: Treat (02,05,2026) as today.", user_content)


if __name__ == "__main__":
    unittest.main()
