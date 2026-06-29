import unittest

from src.schemas.models import EvidenceBackedQuarterSummary, EvidenceClaim
from src.validation.evidence_validator import ValidationResult, filter_quarter_evidence


def _quarter_evidence(**overrides) -> EvidenceBackedQuarterSummary:
    payload = {
        "company_name": "Amazon",
        "quarter": "2024-Q1",
        "what_happened": [
            EvidenceClaim(
                claim="Revenue growth",
                excerpt="Revenue grew strongly in the quarter.",
            )
        ],
        "positives": [],
        "negatives": [],
        "confidence_score": 10,
        "analysis": [],
    }
    payload.update(overrides)
    return EvidenceBackedQuarterSummary(**payload)


class PosNegBackfillTestCase(unittest.TestCase):
    def test_backfill_positives_negatives_from_analysis(self):
        transcript = "Revenue grew strongly. Margins declined due to investment."
        evidence = _quarter_evidence(
            analysis=[
                EvidenceClaim(
                    claim="+10: Revenue growth supports outlook",
                    excerpt="Revenue grew strongly.",
                ),
                EvidenceClaim(
                    claim="-5: Margin pressure",
                    excerpt="Margins declined due to investment.",
                ),
                EvidenceClaim(
                    claim="+3: Demand stable",
                    excerpt="Revenue grew strongly.",
                ),
                EvidenceClaim(
                    claim="+2: Mix improved",
                    excerpt="Revenue grew strongly.",
                ),
            ],
        )
        validation = ValidationResult(is_valid=False, failures=[])
        filtered, backfilled = filter_quarter_evidence(evidence, validation, transcript)

        self.assertIn("positives", backfilled)
        self.assertIn("negatives", backfilled)
        self.assertGreaterEqual(len(filtered.positives), 1)
        self.assertGreaterEqual(len(filtered.negatives), 1)
        self.assertNotIn("+10:", filtered.positives[0].claim)

    def test_existing_positives_are_not_overwritten(self):
        transcript = "Revenue grew strongly."
        evidence = _quarter_evidence(
            positives=[
                EvidenceClaim(
                    claim="Revenue growth",
                    excerpt="Revenue grew strongly.",
                )
            ],
            analysis=[
                EvidenceClaim(
                    claim="+10: Revenue growth supports outlook",
                    excerpt="Revenue grew strongly.",
                ),
            ],
        )
        validation = ValidationResult(is_valid=True, failures=[])
        filtered, backfilled = filter_quarter_evidence(evidence, validation, transcript)

        self.assertEqual(backfilled, [])
        self.assertEqual(len(filtered.positives), 1)
        self.assertEqual(filtered.positives[0].claim, "Revenue growth")


if __name__ == "__main__":
    unittest.main()
