import unittest
from pathlib import Path

from src.ingest.filings.fiscal import (
    fiscal_year_prefix,
    is_q4_quarter,
    normalize_quarter_label,
    parse_quarter_from_filename,
    parse_quarters_list,
    prior_quarter_labels_for_fy_q4,
    quarter_number,
    sibling_quarter_label,
)
from src.ingest.filings.types import FilingLoadError


class FiscalTestCase(unittest.TestCase):
    def test_parse_quarter_from_filename(self):
        self.assertEqual(parse_quarter_from_filename(Path("2024-Q1.txt")), "2024-Q1")
        self.assertEqual(
            parse_quarter_from_filename(Path("MSFT_2025-Q3_transcript.pdf")),
            "2025-Q3",
        )
        self.assertEqual(
            parse_quarter_from_filename(Path("NVDA_FY2025-Q2_earnings.txt")),
            "FY2025-Q2",
        )
        self.assertEqual(
            parse_quarter_from_filename(Path("FY2027-Q1.pdf")),
            "FY2027-Q1",
        )
        self.assertIsNone(parse_quarter_from_filename(Path("transcript.txt")))

    def test_normalize_quarter_label(self):
        self.assertEqual(normalize_quarter_label("FY2025-Q2"), "FY2025-Q2")
        self.assertEqual(normalize_quarter_label("2025-Q2"), "2025-Q2")

    def test_normalize_quarter_label_rejects_invalid(self):
        with self.assertRaises(FilingLoadError):
            normalize_quarter_label("invalid")

    def test_quarter_number_and_q4(self):
        self.assertEqual(quarter_number("FY2025-Q4"), 4)
        self.assertTrue(is_q4_quarter("FY2025-Q4"))
        self.assertFalse(is_q4_quarter("2025-Q2"))

    def test_fiscal_year_prefix(self):
        self.assertEqual(fiscal_year_prefix("FY2025-Q2"), "FY2025")
        self.assertEqual(fiscal_year_prefix("2025-Q2"), "2025")

    def test_sibling_quarter_label(self):
        self.assertEqual(sibling_quarter_label("FY2025", 2), "FY2025-Q2")
        self.assertEqual(sibling_quarter_label("2025", 3), "2025-Q3")

    def test_prior_quarter_labels_for_fy_q4(self):
        self.assertEqual(
            prior_quarter_labels_for_fy_q4("FY2025"),
            ["FY2025-Q1", "FY2025-Q2", "FY2025-Q3"],
        )

    def test_parse_quarters_list(self):
        self.assertEqual(
            parse_quarters_list("FY2026-Q4,FY2026-Q1,FY2026-Q2"),
            ["FY2026-Q1", "FY2026-Q2", "FY2026-Q4"],
        )
        self.assertEqual(parse_quarters_list("FY2026-Q1"), ["FY2026-Q1"])


if __name__ == "__main__":
    unittest.main()
