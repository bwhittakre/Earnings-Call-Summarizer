import unittest

from src.batch.models import BatchQuarterResult
from src.export.csv_writer import batch_result_to_excel_row


class SkippedExcelRowTestCase(unittest.TestCase):
    def test_skipped_row_message(self):
        row = batch_result_to_excel_row(
            BatchQuarterResult(
                quarter_label="2016-Q3",
                status="skipped",
                error_message="API timeout",
                attempts=2,
                last_error="API timeout",
            )
        )
        self.assertIn("SKIPPED after 2 attempts", row["What Happened"])
        self.assertEqual(row["Confidence Score"], "")

    def test_failed_row_message(self):
        row = batch_result_to_excel_row(
            BatchQuarterResult(
                quarter_label="2015-Q4",
                status="failed",
                error_message="No earnings 8-K found",
                attempts=1,
            )
        )
        self.assertIn("EDGAR fetch failed", row["What Happened"])


if __name__ == "__main__":
    unittest.main()
