import unittest

from src.schemas.models import EvidenceBackedQuarterSummary, EvidenceClaim, quarter_summary_from_evidence
from src.scoring.analysis_score import (
    apply_confidence_score_from_analysis,
    compute_confidence_score_from_analysis,
    parse_analysis_weight,
)


class AnalysisScoreTestCase(unittest.TestCase):
    def test_parse_analysis_weight(self):
        self.assertEqual(parse_analysis_weight("+25: Beat and raise"), 25)
        self.assertEqual(parse_analysis_weight("-10: Margin pressure"), -10)
        self.assertIsNone(parse_analysis_weight("No weight prefix"))

    def test_compute_confidence_score_from_analysis(self):
        analysis = [
            EvidenceClaim(claim="+25: Beat", excerpt="Revenue beat guidance."),
            EvidenceClaim(claim="+20: Demand", excerpt="Demand remains strong."),
            EvidenceClaim(claim="-10: Risk", excerpt="Margins may compress."),
        ]
        self.assertEqual(compute_confidence_score_from_analysis(analysis), 35)

    def test_price_trend_bullet_counts_toward_score(self):
        analysis = [
            EvidenceClaim(claim="+20: Beat", excerpt="Revenue beat guidance."),
            EvidenceClaim(
                claim="+10: [price] Upward momentum",
                excerpt="FY2025-Q2 end (2024-07-28, traded 2024-07-26): $123.45",
            ),
        ]
        self.assertEqual(compute_confidence_score_from_analysis(analysis), 30)

    def test_compute_confidence_score_clamps_to_bounds(self):
        analysis = [
            EvidenceClaim(claim="+80: Factor A", excerpt="quote a"),
            EvidenceClaim(claim="+80: Factor B", excerpt="quote b"),
        ]
        self.assertEqual(compute_confidence_score_from_analysis(analysis), 100)

    def test_apply_confidence_score_overrides_llm_score(self):
        evidence = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2025-Q2",
            what_happened=[
                EvidenceClaim(claim="Beat", excerpt="Revenue beat guidance."),
            ],
            positives=[],
            negatives=[],
            confidence_score=82,
            analysis=[
                EvidenceClaim(claim="+25: Beat", excerpt="Revenue beat guidance."),
                EvidenceClaim(claim="+20: Demand", excerpt="Demand remains strong."),
                EvidenceClaim(claim="-10: Risk", excerpt="Margins may compress."),
            ],
        )
        updated = apply_confidence_score_from_analysis(evidence)
        self.assertEqual(updated.confidence_score, 35)

        summary = quarter_summary_from_evidence(evidence)
        self.assertEqual(summary.confidence_score, 35)

    def test_evidence_summary_accepts_more_than_ten_analysis_bullets(self):
        analysis = [
            EvidenceClaim(claim=f"+5: Factor {index}", excerpt=f"quote {index}")
            for index in range(12)
        ]
        evidence = EvidenceBackedQuarterSummary(
            company_name="Nvidia",
            quarter="FY2025-Q2",
            what_happened=[
                EvidenceClaim(claim="Beat", excerpt="Revenue beat guidance."),
            ],
            positives=[],
            negatives=[],
            confidence_score=60,
            analysis=analysis,
        )
        self.assertEqual(len(evidence.analysis), 12)


if __name__ == "__main__":
    unittest.main()
