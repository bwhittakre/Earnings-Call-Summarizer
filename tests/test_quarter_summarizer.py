import unittest
from unittest.mock import MagicMock

from src.llm.quarter_summarizer import QuarterSummarizer
from src.schemas.models import (
    EvidenceBackedQuarterSummary,
    EvidenceClaim,
    LLMResult,
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

    def test_user_content_uses_filings_only(self):
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

        summarizer = QuarterSummarizer(client, skip_rescue_judge=True)
        summarizer.summarize(
            quarter="FY2025-Q2",
            corpus_text=CORPUS,
            label="FY2025-Q2_quarter",
        )

        user_content = client.complete_json.call_args.kwargs["user_content"]
        self.assertNotIn("PRIOR QUARTER STOCK PRICES", user_content)
        self.assertIn("--- FILINGS ---", user_content)
        self.assertEqual(client.complete_json.call_count, 1)

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
