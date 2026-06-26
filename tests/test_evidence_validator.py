import unittest

from pydantic import ValidationError

from src.schemas.models import (
    ConfidenceEvidence,
    EvidenceBackedQuarterSummary,
    EvidenceBackedRollupSummary,
    EvidenceClaim,
    QuarterSummary,
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

SAMPLE_ANALYSIS = [
    EvidenceClaim(
        claim="+20: Raised outlook supports next-quarter momentum",
        excerpt="We saw strong demand in data center and raised our full-year outlook.",
    )
]


def _quarter_evidence(**overrides) -> EvidenceBackedQuarterSummary:
    payload = {
        "company_name": "Nvidia",
        "quarter": "FY2025-Q2",
        "what_happened": [
            EvidenceClaim(
                claim="Strong data center demand",
                excerpt="We saw strong demand in data center and raised our full-year outlook.",
            )
        ],
        "positives": [
            EvidenceClaim(
                claim="Margin expansion",
                excerpt="Margins expanded due to mix.",
            )
        ],
        "negatives": [
            EvidenceClaim(
                claim="FX headwinds",
                excerpt="FX remained a headwind.",
            )
        ],
        "confidence_score": 20,
        "analysis": list(SAMPLE_ANALYSIS),
    }
    payload.update(overrides)
    return EvidenceBackedQuarterSummary(**payload)


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

    def test_excerpt_matches_amazon_style_normalization(self):
        import json
        from pathlib import Path

        cases_path = Path(__file__).parent / "fixtures" / "amazon_audit_cases.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        for case in cases:
            if not case.get("expected_pass"):
                continue
            with self.subTest(case=case["name"]):
                self.assertTrue(
                    excerpt_found_in_source(case["excerpt"], case["source_text"]),
                    case["name"],
                )

    def test_excerpt_rejects_multi_span_amazon_analysis(self):
        import json
        from pathlib import Path

        cases_path = Path(__file__).parent / "fixtures" / "amazon_audit_cases.json"
        cases = json.loads(cases_path.read_text(encoding="utf-8"))
        case = next(item for item in cases if item["name"] == "amazon_multi_span_analysis_excerpt")
        self.assertFalse(
            excerpt_found_in_source(case["excerpt"], case["source_text"]),
        )

    def test_validate_quarter_evidence_passes(self):
        transcript = (
            "We saw strong demand in data center and raised our full-year outlook. "
            "Margins expanded due to mix. FX remained a headwind."
        )
        result = validate_quarter_evidence(_quarter_evidence(), transcript)
        self.assertTrue(result.is_valid)
        self.assertEqual(result.failures, [])

    def test_validate_analysis_accepts_price_block_excerpt(self):
        transcript = (
            "We saw strong demand in data center and raised our full-year outlook. "
            "Margins expanded due to mix. FX remained a headwind."
        )
        price_line = "FY2025-Q2 end (2024-07-28, traded 2024-07-26): $123.45"
        price_block = "\n".join(
            [
                "--- PRIOR QUARTER STOCK PRICES (source: yfinance adjusted close; not from transcript) ---",
                "Ticker: NVDA",
                price_line,
            ]
        )
        evidence = _quarter_evidence(
            analysis=[
                EvidenceClaim(
                    claim="+20: Raised outlook supports next-quarter momentum",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                ),
                EvidenceClaim(
                    claim="+10: [price] Upward momentum across prior quarters",
                    excerpt=price_line,
                ),
            ]
        )
        result = validate_quarter_evidence(
            evidence,
            transcript,
            price_block,
        )
        self.assertTrue(result.is_valid)

    def test_validate_analysis_rejects_price_block_without_prices(self):
        transcript = (
            "We saw strong demand in data center and raised our full-year outlook. "
            "Margins expanded due to mix. FX remained a headwind."
        )
        price_line = "FY2025-Q2 end (2024-07-28, traded 2024-07-26): $123.45"
        evidence = _quarter_evidence(
            analysis=[
                EvidenceClaim(
                    claim="+20: Raised outlook supports next-quarter momentum",
                    excerpt="We saw strong demand in data center and raised our full-year outlook.",
                ),
                EvidenceClaim(
                    claim="+10: [price] Upward momentum across prior quarters",
                    excerpt=price_line,
                ),
            ]
        )
        result = validate_quarter_evidence(evidence, transcript)
        self.assertFalse(result.is_valid)

    def test_validate_quarter_evidence_fails_on_missing_excerpt(self):
        transcript = "We saw strong demand in data center."
        evidence = _quarter_evidence(
            what_happened=[
                EvidenceClaim(
                    claim="Raised guidance",
                    excerpt="We raised full-year guidance across every segment.",
                )
            ],
            positives=[],
            negatives=[],
            analysis=SAMPLE_ANALYSIS,
        )
        result = validate_quarter_evidence(evidence, transcript)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.failures[0].field, "what_happened")

    def test_validate_quarter_evidence_validates_analysis(self):
        transcript = "We saw strong demand in data center and raised our full-year outlook."
        evidence = _quarter_evidence(
            positives=[],
            negatives=[],
            analysis=[
                EvidenceClaim(
                    claim="+10: Demand commentary",
                    excerpt="This quote is not in the transcript at all.",
                )
            ],
        )
        result = validate_quarter_evidence(evidence, transcript)
        self.assertFalse(result.is_valid)
        self.assertEqual(result.failures[0].field, "analysis")

    def test_validate_rollup_evidence_uses_quarter_corpus(self):
        quarter = _quarter_evidence()
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

    def test_summary_conversion_preserves_analysis(self):
        evidence = _quarter_evidence(positives=[], negatives=[])
        summary = quarter_summary_from_evidence(evidence)
        self.assertEqual(summary.what_happened, ["Strong data center demand"])
        self.assertEqual(summary.confidence_score, 20)
        self.assertEqual(len(summary.analysis), 1)
        self.assertEqual(summary.analysis[0].excerpt, SAMPLE_ANALYSIS[0].excerpt)

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

    def test_confidence_score_bounds(self):
        with self.assertRaises(ValidationError):
            QuarterSummary(
                company_name="Nvidia",
                quarter="FY2025-Q2",
                what_happened=["Strong demand"],
                positives=[],
                negatives=[],
                confidence_score=101,
                analysis=SAMPLE_ANALYSIS,
            )

    def test_filter_quarter_evidence_drops_invalid_bullets(self):
        transcript = (
            "We saw strong demand in data center and raised our full-year outlook. "
            "Margins expanded due to mix."
        )
        evidence = _quarter_evidence(
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
        )
        validation = validate_quarter_evidence(evidence, transcript)
        filtered = filter_quarter_evidence(evidence, validation, transcript)
        self.assertEqual(len(filtered.what_happened), 1)
        self.assertEqual(filtered.what_happened[0].claim, "Strong data center demand")
        summary = quarter_summary_from_evidence(filtered)
        self.assertEqual(len(summary.what_happened), 1)


if __name__ == "__main__":
    unittest.main()
