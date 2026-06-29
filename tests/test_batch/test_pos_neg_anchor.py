import unittest

from src.schemas.models import EvidenceBackedQuarterSummary, EvidenceClaim
from src.validation.evidence_processor import process_quarter_evidence_strict

_SAMPLE_ANALYSIS = [
    EvidenceClaim(
        claim="+10: AWS revenue growth supports outlook",
        excerpt="AWS revenue grew 40% year over year in the first quarter.",
    )
]


class PosNegAnchorTestCase(unittest.TestCase):
    def test_pre_anchor_fixes_invalid_pos_neg_excerpt(self):
        corpus = "\n".join(
            [
                "--- EARNINGS PRESS RELEASE ---",
                "AWS revenue grew 40% year over year in the first quarter.",
                "",
                "--- 10-K ---",
                "AWS revenue grew forty percent year over year in the first quarter.",
            ]
        )
        evidence = EvidenceBackedQuarterSummary(
            company_name="Amazon",
            quarter="2024-Q1",
            what_happened=[
                EvidenceClaim(
                    claim="AWS revenue growth",
                    excerpt="AWS revenue grew 40% year over year in the first quarter.",
                )
            ],
            positives=[
                EvidenceClaim(
                    claim="AWS revenue growth",
                    excerpt="AWS grew forty percent year over year",
                )
            ],
            negatives=[],
            confidence_score=10,
            analysis=list(_SAMPLE_ANALYSIS),
        )

        result = process_quarter_evidence_strict(evidence, corpus)

        self.assertTrue(result.auto_anchored)
        self.assertEqual(len(result.evidence.positives), 1)
        self.assertIn("40%", result.evidence.positives[0].excerpt)

    def test_pos_neg_validation_uses_press_release_section_only(self):
        from src.ingest.documents.corpus import pos_neg_validation_source
        from src.validation.evidence_validator import validate_quarter_evidence

        corpus = "\n".join(
            [
                "--- EARNINGS PRESS RELEASE ---",
                "Operating income rose 18% year over year.",
                "",
                "--- 10-K ---",
                "Operating income rose eighteen percent year over year.",
            ]
        )
        pos_neg_source = pos_neg_validation_source(corpus)
        evidence = EvidenceBackedQuarterSummary(
            company_name="Amazon",
            quarter="2024-Q1",
            what_happened=[
                EvidenceClaim(
                    claim="Operating income growth",
                    excerpt="Operating income rose 18% year over year.",
                )
            ],
            positives=[
                EvidenceClaim(
                    claim="Operating income growth",
                    excerpt="Operating income rose 18% year over year.",
                )
            ],
            negatives=[],
            confidence_score=10,
            analysis=list(_SAMPLE_ANALYSIS),
        )
        validation = validate_quarter_evidence(
            evidence,
            corpus,
            pos_neg_source=pos_neg_source,
        )
        pos_failures = [item for item in validation.failures if item.field == "positives"]
        self.assertEqual(pos_failures, [])


if __name__ == "__main__":
    unittest.main()
