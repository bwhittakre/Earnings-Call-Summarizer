import unittest

from src.schemas.models import (
    ConfidenceEvidence,
    EvidenceBackedQuarterSummary,
    EvidenceBackedRollupSummary,
    EvidenceClaim,
    quarter_summary_from_evidence,
    rollup_summary_from_evidence,
)
from src.validation.evidence_validator import (
    build_quarter_evidence_corpus,
    excerpt_found_in_source,
    filter_quarter_evidence,
    normalize_text,
    validate_quarter_evidence,
    validate_rollup_evidence,
)


class EvidenceValidatorTestCase(unittest.TestCase):
    def test_normalize_text_collapses_whitespace(self):
        self.assertEqual(
            normalize_text("Revenue  grew\r\n\tstrongly"),
            "revenue grew strongly",
        )

    def test_excerpt_found_in_source(self):
        source = "Management said revenue grew strongly in the data center segment."
        self.assertTrue(
            excerpt_found_in_source(
                "revenue grew strongly in the data center",
                source,
            )
        )
        self.assertFalse(
            excerpt_found_in_source(
                "revenue declined sharply",
                source,
            )
        )

    def test_excerpt_rejects_short_quotes(self):
        source = "Revenue grew strongly in the data center segment."
        self.assertFalse(excerpt_found_in_source("Revenue grew", source))

    def test_validate_quarter_evidence_passes(self):
        transcript = (
            "We saw strong demand in data center and raised our full-year outlook. "
            "Margins expanded due to mix. FX remained a headwind."
        )
        evidence = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2025-Q2",
            what_happened=[
                EvidenceClaim(
                    claim="Strong data center demand",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                )
            ],
            positives=[
                EvidenceClaim(
                    claim="Margin expansion",
                    excerpt="Margins expanded due to mix.",
                )
            ],
            negatives=[
                EvidenceClaim(
                    claim="FX headwinds",
                    excerpt="FX remained a headwind.",
                )
            ],
            confidence=ConfidenceEvidence(
                level="High",
                excerpt="We saw strong demand in data center and raised our full-year outlook.",
            ),
        )
        result = validate_quarter_evidence(evidence, transcript)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.failures, [])

    def test_validate_quarter_evidence_fails_on_missing_excerpt(self):
        transcript = "We saw strong demand in data center."
        evidence = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2025-Q2",
            what_happened=[
                EvidenceClaim(
                    claim="Raised guidance",
                    excerpt="We raised full-year guidance across every segment.",
                )
            ],
            positives=[],
            negatives=[],
            confidence=ConfidenceEvidence(
                level="Medium",
                excerpt="We saw strong demand in data center.",
            ),
        )
        result = validate_quarter_evidence(evidence, transcript)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.failures[0].field, "what_happened")

    def test_validate_rollup_evidence_uses_quarter_corpus(self):
        quarter = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2025-Q2",
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
        rollup = EvidenceBackedRollupSummary(
            company_name="Nvidia",
            what_happened=[
                EvidenceClaim(
                    claim="Data center strength",
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
        result = validate_rollup_evidence(rollup, [quarter])
        self.assertTrue(result.is_valid)
        self.assertIn(
            "We saw strong demand in data center and raised our full-year outlook.",
            build_quarter_evidence_corpus([quarter]),
        )

    def test_summary_conversion_strips_evidence(self):
        evidence = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2025-Q2",
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
        summary = quarter_summary_from_evidence(evidence)
        self.assertEqual(summary.what_happened, ["Strong data center demand"])
        self.assertEqual(summary.confidence, "High")

        rollup = rollup_summary_from_evidence(
            EvidenceBackedRollupSummary(
                company_name="Nvidia",
                what_happened=[
                    EvidenceClaim(
                        claim="Data center strength",
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
        )
        self.assertEqual(rollup.summary_type, "rollup")

    def test_filter_quarter_evidence_drops_invalid_bullets(self):
        transcript = (
            "We saw strong demand in data center and raised our full-year outlook. "
            "Margins expanded due to mix."
        )
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
                    excerpt="We raised full-year guidance across every segment.",
                ),
            ],
            positives=[],
            negatives=[],
            confidence=ConfidenceEvidence(
                level="High",
                excerpt="We saw strong demand in data center and raised our full-year outlook.",
            ),
        )
        validation = validate_quarter_evidence(evidence, transcript)
        filtered = filter_quarter_evidence(evidence, validation, transcript)
        self.assertEqual(len(filtered.what_happened), 1)
        self.assertEqual(filtered.what_happened[0].claim, "Strong data center demand")
        summary = quarter_summary_from_evidence(filtered)
        self.assertEqual(len(summary.what_happened), 1)


if __name__ == "__main__":
    unittest.main()
