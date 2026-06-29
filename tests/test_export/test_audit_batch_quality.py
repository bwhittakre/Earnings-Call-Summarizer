import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import Workbook

from scripts.audit_batch_quality import audit_workbook


class AuditBatchQualityTestCase(unittest.TestCase):
    def test_audit_reads_fetch_summary_and_validated_factors(self):
        workbook = Workbook()
        backtest = workbook.active
        backtest.title = "Batch Backtest"
        backtest.append(["Confidence Score uses Edgar documents only."])
        backtest.append(
            [
                "Quarter",
                "What Happened",
                "Positives",
                "Negatives",
                "Document-Only Score",
                "Confidence Score",
                "Analysis",
                "Fetch Summary",
            ]
        )
        backtest.append(
            [
                "FY2025-Q2",
                "- Revenue up",
                "- Cloud growth",
                "- FX headwind",
                12,
                12,
                "• +12: Revenue — \"Revenue up.\"",
                "PR + Commentary + 8-K; Transcript(found)",
            ]
        )

        factors = workbook.create_sheet("Validated Factors")
        factors.append(["note"])
        factors.append(["Quarter", "Source", "Field", "Claim", "Excerpt", "In Score?"])
        factors.append(["FY2025-Q2", "Filing", "analysis", "+12: Revenue", "Revenue up.", "Yes"])
        factors.append(["FY2025-Q2", "Transcript", "positives", "Call tone", "demand strong", "No"])

        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.xlsx"
            workbook.save(path)
            rows = audit_workbook(path, None)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["quarter"], "FY2025-Q2")
        self.assertEqual(row["docs_fetched"], 3)
        self.assertTrue(row["transcript_available"])
        self.assertEqual(row["validated_factor_count"], 2)
        self.assertFalse(row["blank_positives"])
        self.assertFalse(row["blank_negatives"])


if __name__ == "__main__":
    unittest.main()
