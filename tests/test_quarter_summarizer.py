import unittest
from unittest.mock import MagicMock

from src.llm.quarter_summarizer import QuarterSummarizer
from src.schemas.models import (
    EvidenceBackedQuarterSummary,
    EvidenceClaim,
    LLMResult,
    TokenUsage,
)

TRANSCRIPT = (
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
            transcript_text=TRANSCRIPT,
            label="FY2025-Q2_quarter",
        )

        self.assertEqual(output.summary.company_name, "Amazon")
        self.assertEqual(output.evidence.company_name, "Amazon")

    def test_includes_price_block_in_user_content(self):
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

        price_block = (
            "--- PRIOR QUARTER STOCK PRICES (source: yfinance adjusted close; not from transcript) ---\n"
            "Ticker: AMZN\n"
            "FY2024-Q3 end (2024-09-30, traded 2024-09-30): $186.00"
        )
        summarizer = QuarterSummarizer(client, skip_rescue_judge=True)
        summarizer.summarize(
            quarter="FY2025-Q2",
            transcript_text=TRANSCRIPT,
            label="FY2025-Q2_quarter",
            price_block_text=price_block,
        )

        user_content = client.complete_json.call_args.kwargs["user_content"]
        self.assertIn("PRIOR QUARTER STOCK PRICES", user_content)
        self.assertIn(price_block, user_content)
        self.assertIn("--- DOCUMENT CORPUS ---", user_content)


if __name__ == "__main__":
    unittest.main()
