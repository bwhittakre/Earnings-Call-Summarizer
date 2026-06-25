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


if __name__ == "__main__":
    unittest.main()
