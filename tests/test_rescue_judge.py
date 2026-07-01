import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.llm.quarter_summarizer import QuarterSummarizer
from src.schemas.models import (
    EvidenceBackedQuarterSummary,
    EvidenceClaim,
    LLMResult,
    RescueJudgeResult,
    RescueReview,
    TokenUsage,
    quarter_summary_from_evidence,
)
from src.validation.evidence_processor import (
    QUOTE_ANCHOR_REASON,
    apply_rescue_reviews_to_quarter,
    process_quarter_evidence_strict,
)
from src.validation.evidence_validator import validate_quarter_evidence
from src.validation.quote_anchor import find_verbatim_quote
from src.validation.rescue_judge import RescueJudge
from src.validation.rescue_orchestrator import augment_rescue_reviews_with_retries

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "rescue_golden_cases.json"

CORPUS = (
    "We saw strong demand in data center and raised our full-year outlook. "
    "Margins expanded due to mix. FX remained a headwind."
)

SAMPLE_ANALYSIS = [
    EvidenceClaim(
        claim="+20: Raised outlook supports next-quarter momentum",
        excerpt="We saw strong demand in data center and raised our full-year outlook.",
    )
]


def _quarter_evidence(**overrides) -> EvidenceBackedQuarterSummary:
    payload = {
        "company_name": "Nvidia",
        "quarter": "FY2026-Q1",
        "what_happened": [
            EvidenceClaim(
                claim="Strong data center demand",
                excerpt="We saw strong demand in data center and raised our full-year outlook.",
            )
        ],
        "positives": [],
        "negatives": [],
        "confidence_score": 20,
        "analysis": list(SAMPLE_ANALYSIS),
    }
    payload.update(overrides)
    return EvidenceBackedQuarterSummary(**payload)


class RescueJudgeTestCase(unittest.TestCase):
    def test_apply_rescue_reviews_keeps_verbatim_and_rescues_paraphrase(self):
        evidence = _quarter_evidence(
            what_happened=[
                EvidenceClaim(
                    claim="Strong data center demand",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                ),
                EvidenceClaim(
                    claim="Raised guidance",
                    excerpt="Management raised full-year outlook on data center strength.",
                ),
            ]
        )
        validation = validate_quarter_evidence(evidence, CORPUS)
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
            CORPUS,
        )
        self.assertEqual(len(processed.evidence.what_happened), 2)
        self.assertEqual(len(processed.rescued), 1)
        self.assertEqual(processed.rescued[0].claim, "Raised guidance")
        self.assertEqual(len(processed.dropped), 0)

    def test_apply_rescue_reviews_drops_invalid_claim_with_drop_stage(self):
        evidence = _quarter_evidence(
            what_happened=[
                EvidenceClaim(
                    claim="Revenue collapse",
                    excerpt="Revenue declined sharply across all segments.",
                )
            ]
        )
        validation = validate_quarter_evidence(evidence, CORPUS)
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
            CORPUS,
        )
        self.assertEqual(len(processed.dropped), 1)
        self.assertEqual(processed.dropped[0].drop_stage, "judge_rejected")
        self.assertEqual(processed.dropped[0].verdict, "drop")
        self.assertGreaterEqual(len(processed.evidence.what_happened), 1)

    def test_quote_anchor_rescues_bad_canonical_excerpt(self):
        source = (
            "Operating income was $21.2 billion, up 61% year over year, "
            "and trailing 12-month free cash flow was $36.2 billion."
        )
        evidence = EvidenceBackedQuarterSummary(
            company_name="Amazon",
            quarter="FY2025-Q4",
            what_happened=[
                EvidenceClaim(
                    claim="Record quarterly operating income of $21.2B, up 61% YoY",
                    excerpt=(
                        "Operating income was $21.2 billion, up 61% year over year, "
                        "and trailing 12-month free cash flow was strong."
                    ),
                )
            ],
            positives=[],
            negatives=[],
            confidence_score=80,
            analysis=[
                EvidenceClaim(
                    claim="+25: Record operating income",
                    excerpt=(
                        "Operating income was $21.2 billion, up 61% year over year, "
                        "and trailing 12-month free cash flow was $36.2 billion."
                    ),
                )
            ],
        )
        validation = validate_quarter_evidence(evidence, source)
        rescue_result = RescueJudgeResult(
            reviews=[
                RescueReview(
                    field="what_happened",
                    index=0,
                    verdict="rescued",
                    reason="Source states operating income was $21.2 billion, up 61% year over year.",
                    canonical_excerpt="Operating income was $21.2B, up sixty-one percent YoY.",
                )
            ]
        )
        processed = apply_rescue_reviews_to_quarter(
            evidence,
            validation,
            rescue_result,
            source,
        )
        self.assertEqual(len(processed.evidence.what_happened), 1)
        self.assertEqual(len(processed.dropped), 0)
        self.assertEqual(len(processed.rescued), 1)
        self.assertEqual(processed.rescued[0].reason, QUOTE_ANCHOR_REASON)

    def test_drop_stage_canonical_failed_when_rescued_without_anchor(self):
        evidence = _quarter_evidence(
            what_happened=[
                EvidenceClaim(
                    claim="Revenue collapse across all segments",
                    excerpt="Revenue declined sharply across all segments.",
                )
            ]
        )
        validation = validate_quarter_evidence(evidence, CORPUS)
        rescue_result = RescueJudgeResult(
            reviews=[
                RescueReview(
                    field="what_happened",
                    index=0,
                    verdict="rescued",
                    reason="Supported by transcript.",
                    canonical_excerpt="This quote does not exist in the transcript at all.",
                )
            ]
        )
        processed = apply_rescue_reviews_to_quarter(
            evidence,
            validation,
            rescue_result,
            CORPUS,
        )
        self.assertEqual(len(processed.dropped), 1)
        self.assertEqual(processed.dropped[0].drop_stage, "canonical_failed_verbatim")
        self.assertEqual(processed.dropped[0].verdict, "rescued")

    def test_find_verbatim_quote_from_golden_cases(self):
        cases = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
        for case in cases:
            quote = find_verbatim_quote(
                case["claim"],
                case["source_text"],
                hint_excerpt=case["excerpt"],
            )
            if case["expected_kept"]:
                self.assertIsNotNone(
                    quote,
                    msg=f"Expected quote anchor for case {case['name']}",
                )

    def test_augment_rescue_reviews_retries_bad_canonical(self):
        failure = validate_quarter_evidence(
            EvidenceBackedQuarterSummary(
                company_name="Amazon",
                quarter="FY2025-Q4",
                what_happened=[
                    EvidenceClaim(
                        claim="Record quarterly operating income of $21.2B, up 61% YoY",
                        excerpt="Operating income paraphrase that is not verbatim.",
                    )
                ],
                positives=[],
                negatives=[],
                confidence_score=80,
                analysis=[
                    EvidenceClaim(
                        claim="+25: Record operating income",
                        excerpt="Operating income was $21.2 billion, up 61% year over year.",
                    )
                ],
            ),
            "Operating income was $21.2 billion, up 61% year over year.",
        ).failures[0]
        initial = RescueJudgeResult(
            reviews=[
                RescueReview(
                    field=failure.field,
                    index=failure.index,
                    verdict="rescued",
                    reason="Supported.",
                    canonical_excerpt="Not a verbatim quote from source.",
                )
            ]
        )
        retry_review = RescueReview(
            field=failure.field,
            index=failure.index,
            verdict="rescued",
            reason="Copied exactly.",
            canonical_excerpt="Operating income was $21.2 billion, up 61% year over year.",
        )
        rescue_judge = MagicMock(spec=RescueJudge)
        rescue_judge.review_single_failure.return_value = (
            RescueJudgeResult(reviews=[retry_review]),
            LLMResult(usage=TokenUsage(input_tokens=1, output_tokens=1), raw_response="{}"),
        )

        augmented = augment_rescue_reviews_with_retries(
            rescue_judge,
            [failure],
            initial,
            "Operating income was $21.2 billion, up 61% year over year.",
            "Amazon_FY2025-Q4_quarter",
        )
        rescue_judge.review_single_failure.assert_called_once()
        self.assertEqual(augmented.reviews[0].canonical_excerpt, retry_review.canonical_excerpt)

    def test_strict_mode_drops_paraphrase_without_rescue(self):
        evidence = _quarter_evidence(
            what_happened=[
                EvidenceClaim(
                    claim="Strong data center demand",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                ),
                EvidenceClaim(
                    claim="Raised guidance",
                    excerpt="Management raised full-year outlook on data center strength.",
                ),
            ]
        )
        processed = process_quarter_evidence_strict(evidence, CORPUS)
        self.assertEqual(len(processed.evidence.what_happened), 1)
        self.assertEqual(len(processed.dropped), 1)

    def test_apply_rescue_reviews_rescues_analysis(self):
        evidence = _quarter_evidence(
            analysis=[
                EvidenceClaim(
                    claim="+15: Margin expansion supports outlook",
                    excerpt="Margins expanded meaningfully due to favorable mix.",
                )
            ]
        )
        validation = validate_quarter_evidence(evidence, CORPUS)
        self.assertFalse(validation.is_valid)

        rescue_result = RescueJudgeResult(
            reviews=[
                RescueReview(
                    field="analysis",
                    index=0,
                    verdict="rescued",
                    reason="Faithful paraphrase of margin commentary.",
                    canonical_excerpt="Margins expanded due to mix.",
                )
            ]
        )
        processed = apply_rescue_reviews_to_quarter(
            evidence,
            validation,
            rescue_result,
            CORPUS,
        )
        self.assertEqual(len(processed.evidence.analysis), 1)
        self.assertEqual(len(processed.rescued), 1)
        self.assertEqual(processed.rescued[0].field, "analysis")

    @patch.object(RescueJudge, "review_failures")
    def test_quarter_summarizer_single_extract_with_rescue(
        self,
        mock_review,
    ):
        evidence = _quarter_evidence(
            what_happened=[
                EvidenceClaim(
                    claim="Strong data center demand",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                ),
                EvidenceClaim(
                    claim="Raised guidance",
                    excerpt="Completely fabricated sentence not present in the transcript.",
                ),
            ]
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
        output, _ = summarizer.summarize(
            quarter="FY2026-Q1",
            corpus_text=CORPUS,
            label="FY2026-Q1_quarter",
        )

        self.assertEqual(client.complete_json.call_count, 1)
        mock_review.assert_called_once()
        self.assertEqual(len(output.summary.what_happened), 2)
        self.assertEqual(output.summary.confidence_score, 20)
        self.assertEqual(output.summary.company_name, "Nvidia")

    def test_quarter_summarizer_skips_rescue_when_all_verbatim(
        self,
    ):
        evidence = _quarter_evidence()
        client = MagicMock()
        client.complete_json.return_value = (
            evidence,
            LLMResult(usage=TokenUsage(input_tokens=10, output_tokens=5), raw_response="{}"),
        )

        summarizer = QuarterSummarizer(client, skip_rescue_judge=False)
        output, _ = summarizer.summarize(
            quarter="FY2026-Q1",
            corpus_text=CORPUS,
            label="FY2026-Q1_quarter",
        )

        self.assertEqual(client.complete_json.call_count, 1)
        summary = quarter_summary_from_evidence(output.evidence)
        self.assertEqual(summary.what_happened, ["Strong data center demand"])
        self.assertEqual(summary.confidence_score, 20)
        self.assertEqual(summary.company_name, "Nvidia")


if __name__ == "__main__":
    unittest.main()
