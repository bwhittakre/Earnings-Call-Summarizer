import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from src.schemas.models import EvidenceBackedQuarterSummary, EvidenceClaim
from src.validation.evidence_processor import (
    pre_anchor_quarter_failures,
    process_quarter_evidence_with_rescue,
)
from src.validation.evidence_validator import validate_quarter_evidence
from src.validation.quote_anchor import find_verbatim_quote
from src.validation.rescue_judge import RescueJudge

FIXTURES_PATH = Path(__file__).parent / "fixtures" / "amazon_audit_cases.json"


class PreAnchorTestCase(unittest.TestCase):
    def test_pre_anchor_recovers_multi_span_analysis_without_rescue_judge(self):
        cases = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
        case = next(item for item in cases if item["name"] == "amazon_multi_span_analysis_excerpt")

        evidence = EvidenceBackedQuarterSummary(
            company_name="Amazon",
            quarter="FY2026-Q2",
            what_happened=[
                EvidenceClaim(
                    claim="Strong AWS demand",
                    excerpt="AWS grew 17.5% year over year and now has over a 123,000,000,000 annualized revenue run rate.",
                )
            ],
            positives=[],
            negatives=[],
            confidence_score=10,
            analysis=[
                EvidenceClaim(
                    claim=case["claim"],
                    excerpt=case["excerpt"],
                )
            ],
        )
        validation = validate_quarter_evidence(evidence, case["source_text"])
        self.assertFalse(validation.is_valid)

        updated, auto_anchored, remaining = pre_anchor_quarter_failures(
            evidence,
            validation.failures,
            case["source_text"],
        )
        self.assertEqual(len(auto_anchored), 1)
        self.assertEqual(remaining, [])
        self.assertTrue(validate_quarter_evidence(updated, case["source_text"]).is_valid)

    def test_process_quarter_evidence_with_rescue_skips_judge_when_pre_anchor_succeeds(self):
        cases = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
        case = next(item for item in cases if item["name"] == "amazon_multi_span_analysis_excerpt")

        evidence = EvidenceBackedQuarterSummary(
            company_name="Amazon",
            quarter="FY2026-Q2",
            what_happened=[
                EvidenceClaim(
                    claim="Strong AWS demand",
                    excerpt="AWS grew 17.5% year over year and now has over a 123,000,000,000 annualized revenue run rate.",
                )
            ],
            positives=[],
            negatives=[],
            confidence_score=10,
            analysis=[
                EvidenceClaim(
                    claim=case["claim"],
                    excerpt=case["excerpt"],
                )
            ],
        )
        rescue_judge = MagicMock(spec=RescueJudge)
        processed = process_quarter_evidence_with_rescue(
            evidence,
            case["source_text"],
            rescue_judge,
            "FY2026-Q2_quarter",
        )
        rescue_judge.review_failures.assert_not_called()
        self.assertEqual(len(processed.auto_anchored), 1)
        self.assertEqual(processed.rescued, [])
        self.assertEqual(processed.dropped, [])

    def test_amazon_audit_cases_anchor_when_expected(self):
        cases = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
        for case in cases:
            if not case.get("expected_anchor"):
                continue
            with self.subTest(case=case["name"]):
                quote = find_verbatim_quote(
                    case.get("claim", "claim"),
                    case["source_text"],
                    hint_excerpt=case["excerpt"],
                )
                self.assertIsNotNone(quote, case["name"])

    def test_amazon_audit_failures_mostly_pre_anchor_without_rescue_judge(self):
        from src.ingest.loader import load_transcripts

        loaded = load_transcripts(
            Path("data/transcripts/amazon/FY2026-Q2.txt"),
            expected_quarters=1,
        )
        transcript = next(iter(loaded.transcripts.values()))
        audit_excerpts = [
            (
                "what_happened",
                "Revenue and operating income beat guidance",
                "Operating income was $19,200,000,000, which is $1,700,000,000 above the high end of our guidance range.",
            ),
            (
                "positives",
                "Record Prime Day with best-ever sales and Prime sign-ups",
                "This year's Prime Day was our biggest ever with record sales, number of items sold, and number of Prime sign ups in the three weeks leading up to the Prime Day.",
            ),
            (
                "negatives",
                "AWS operating margin declined sharply QoQ from record 39.5% to 32.9%",
                "We did see AWS segment margins decline from a record high of 39.5% in Q1 to 32.9% in Q2.",
            ),
            (
                "analysis",
                "+15: AWS revenue growth and $195B backlog signal durable cloud demand",
                "AWS grew 17.5% year over year and now has over a $123,000,000,000 annualized revenue run rate... backlog was $195,000,000,000, up about 25% year over year.",
            ),
        ]
        evidence = EvidenceBackedQuarterSummary(
            company_name="Amazon",
            quarter="FY2026-Q2",
            what_happened=[
                EvidenceClaim(claim=audit_excerpts[0][1], excerpt=audit_excerpts[0][2])
            ],
            positives=[
                EvidenceClaim(claim=audit_excerpts[1][1], excerpt=audit_excerpts[1][2])
            ],
            negatives=[
                EvidenceClaim(claim=audit_excerpts[2][1], excerpt=audit_excerpts[2][2])
            ],
            confidence_score=10,
            analysis=[
                EvidenceClaim(claim=audit_excerpts[3][1], excerpt=audit_excerpts[3][2])
            ],
        )
        validation = validate_quarter_evidence(evidence, transcript)
        self.assertFalse(validation.is_valid)
        self.assertLessEqual(
            len(validation.failures),
            2,
            "Enhanced Pass 1 matching should accept most Amazon audit excerpts",
        )
        updated, auto_anchored, remaining = pre_anchor_quarter_failures(
            evidence,
            validation.failures,
            transcript,
        )
        self.assertEqual(len(remaining), 0)
        self.assertTrue(validate_quarter_evidence(updated, transcript).is_valid)


if __name__ == "__main__":
    unittest.main()
