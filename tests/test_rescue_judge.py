import unittest
from unittest.mock import MagicMock, patch

from src.llm.quarter_summarizer import QuarterSummarizer
from src.schemas.models import (
    ConfidenceEvidence,
    EvidenceBackedQuarterSummary,
    EvidenceClaim,
    LLMResult,
    RescueJudgeResult,
    RescueReview,
    TokenUsage,
    quarter_summary_from_evidence,
)
from src.validation.evidence_processor import (
    apply_rescue_reviews_to_quarter,
    process_quarter_evidence_strict,
)
from src.validation.evidence_validator import validate_quarter_evidence
from src.validation.rescue_judge import RescueJudge


TRANSCRIPT = (
    "We saw strong demand in data center and raised our full-year outlook. "
    "Margins expanded due to mix. FX remained a headwind."
)


class RescueJudgeTestCase(unittest.TestCase):
    def test_apply_rescue_reviews_keeps_verbatim_and_rescues_paraphrase(self):
        evidence = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2026-Q1",
            what_happened=[
                EvidenceClaim(
                    claim="Strong data center demand",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                ),
                EvidenceClaim(
                    claim="Raised guidance",
                    excerpt="Management raised full-year outlook on data center strength.",
                ),
            ],
            positives=[],
            negatives=[],
            confidence=ConfidenceEvidence(
                level="High",
                excerpt="We saw strong demand in data center and raised our full-year outlook.",
            ),
        )
        validation = validate_quarter_evidence(evidence, TRANSCRIPT)
        self.assertFalse(validation.is_valid)

        rescue_result = RescueJudgeResult(
            reviews=[
                RescueReview(
                    field="what_happened",
                    index=1,
                    verdict="rescued",
                    reason="Faithful paraphrase of guidance raise.",
                    canonical_excerpt="We saw strong demand in data center and raised our full-year outlook.",
                )
            ]
        )
        processed = apply_rescue_reviews_to_quarter(
            evidence,
            validation,
            rescue_result,
            TRANSCRIPT,
        )
        self.assertEqual(len(processed.evidence.what_happened), 2)
        self.assertEqual(len(processed.rescued), 1)
        self.assertEqual(processed.rescued[0].claim, "Raised guidance")
        self.assertEqual(len(processed.dropped), 0)

    def test_apply_rescue_reviews_drops_invalid_claim(self):
        evidence = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2026-Q1",
            what_happened=[
                EvidenceClaim(
                    claim="Revenue collapse",
                    excerpt="Revenue declined sharply across all segments.",
                )
            ],
            positives=[],
            negatives=[],
            confidence=ConfidenceEvidence(
                level="Medium",
                excerpt="We saw strong demand in data center and raised our full-year outlook.",
            ),
        )
        validation = validate_quarter_evidence(evidence, TRANSCRIPT)
        rescue_result = RescueJudgeResult(
            reviews=[
                RescueReview(
                    field="what_happened",
                    index=0,
                    verdict="drop",
                    reason="Unsupported by transcript.",
                    canonical_excerpt=None,
                )
            ]
        )
        processed = apply_rescue_reviews_to_quarter(
            evidence,
            validation,
            rescue_result,
            TRANSCRIPT,
        )
        self.assertEqual(len(processed.dropped), 1)
        self.assertGreaterEqual(len(processed.evidence.what_happened), 1)

    def test_strict_mode_drops_paraphrase_without_rescue(self):
        evidence = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2026-Q1",
            what_happened=[
                EvidenceClaim(
                    claim="Strong data center demand",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                ),
                EvidenceClaim(
                    claim="Raised guidance",
                    excerpt="Management raised full-year outlook on data center strength.",
                ),
            ],
            positives=[],
            negatives=[],
            confidence=ConfidenceEvidence(
                level="High",
                excerpt="We saw strong demand in data center and raised our full-year outlook.",
            ),
        )
        processed = process_quarter_evidence_strict(evidence, TRANSCRIPT)
        self.assertEqual(len(processed.evidence.what_happened), 1)
        self.assertEqual(len(processed.dropped), 1)

    @patch.object(RescueJudge, "review_validation_result")
    def test_quarter_summarizer_single_extract_with_rescue(
        self,
        mock_review,
    ):
        evidence = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2026-Q1",
            what_happened=[
                EvidenceClaim(
                    claim="Strong data center demand",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                ),
                EvidenceClaim(
                    claim="Raised guidance",
                    excerpt="Management raised full-year outlook on data center strength.",
                ),
            ],
            positives=[],
            negatives=[],
            confidence=ConfidenceEvidence(
                level="High",
                excerpt="We saw strong demand in data center and raised our full-year outlook.",
            ),
        )
        client = MagicMock()
        client.complete_json.return_value = (
            evidence,
            LLMResult(usage=TokenUsage(input_tokens=10, output_tokens=5), raw_response="{}"),
        )
        mock_review.return_value = (
            RescueJudgeResult(
                reviews=[
                    RescueReview(
                        field="what_happened",
                        index=1,
                        verdict="rescued",
                        reason="Paraphrase ok.",
                        canonical_excerpt="We saw strong demand in data center and raised our full-year outlook.",
                    )
                ]
            ),
            LLMResult(usage=TokenUsage(input_tokens=3, output_tokens=2), raw_response="{}"),
        )

        summarizer = QuarterSummarizer(client, skip_rescue_judge=False)
        output, _ = summarizer.summarize("Nvidia", "FY2026-Q1", TRANSCRIPT)

        self.assertEqual(client.complete_json.call_count, 1)
        mock_review.assert_called_once()
        self.assertEqual(len(output.summary.what_happened), 2)

    def test_quarter_summarizer_skips_rescue_when_all_verbatim(
        self,
    ):
        evidence = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2026-Q1",
            what_happened=[
                EvidenceClaim(
                    claim="Strong data center demand",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                )
            ],
            positives=[],
            negatives=[],
            confidence=ConfidenceEvidence(
                level="High",
                excerpt="We saw strong demand in data center and raised our full-year outlook.",
            ),
        )
        client = MagicMock()
        client.complete_json.return_value = (
            evidence,
            LLMResult(usage=TokenUsage(input_tokens=10, output_tokens=5), raw_response="{}"),
        )

        summarizer = QuarterSummarizer(client, skip_rescue_judge=False)
        output, _ = summarizer.summarize("Nvidia", "FY2026-Q1", TRANSCRIPT)

        self.assertEqual(client.complete_json.call_count, 1)
        summary = quarter_summary_from_evidence(output.evidence)
        self.assertEqual(summary.what_happened, ["Strong data center demand"])


if __name__ == "__main__":
    unittest.main()
