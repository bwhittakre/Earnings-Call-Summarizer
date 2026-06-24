import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import load_workbook

from src.export.csv_writer import (
    format_bullets,
    format_list,
    format_what_happened,
    summary_to_excel_row,
    summary_to_row,
    write_excel,
)
from src.ingest.loader import assign_quarters, parse_quarter_from_filename
from src.schemas.models import QuarterSummary


class BasicsTestCase(unittest.TestCase):
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

    def test_assign_quarters_fiscal_sorted(self):
        files = [
            Path("FY2027-Q1.txt"),
            Path("FY2025-Q2.txt"),
            Path("FY2026-Q4.txt"),
        ]
        assigned = assign_quarters(files)
        self.assertEqual(
            [item.quarter for item in assigned],
            ["FY2025-Q2", "FY2026-Q4", "FY2027-Q1"],
        )

    def test_assign_quarters_sorted(self):
        files = [
            Path("2024-Q2.txt"),
            Path("2024-Q1.txt"),
            Path("2024-Q3.txt"),
        ]
        assigned = assign_quarters(files)
        self.assertEqual(
            [item.quarter for item in assigned],
            ["2024-Q1", "2024-Q2", "2024-Q3"],
        )

    def test_csv_row_formatting(self):
        summary = QuarterSummary(
            company_name="Microsoft",
            quarter="2024-Q3",
            what_happened=["Strong Azure demand", "Raised guidance"],
            positives=["Cloud growth", "Margin expansion"],
            negatives=["FX headwinds"],
            confidence="High",
        )
        row = summary_to_row(summary)
        self.assertEqual(row["what_happened"], "Strong Azure demand & Raised guidance")
        self.assertEqual(row["positives"], "Cloud growth, Margin expansion")
        self.assertEqual(format_what_happened(["A", "B"]), "A & B")
        self.assertEqual(format_list(["X", "Y"]), "X, Y")
        self.assertEqual(format_bullets(["X", "Y"]), "- X\n- Y")

    def test_excel_row_formatting(self):
        summary = QuarterSummary(
            company_name="Nvidia",
            quarter="FY2025-Q2",
            what_happened=["Strong data center demand", "Raised guidance"],
            positives=["Blackwell ramp", "Margin recovery"],
            negatives=["China restrictions"],
            confidence="High",
        )
        row = summary_to_excel_row(summary)
        self.assertEqual(row["Summary Type"], "Quarter")
        self.assertEqual(row["What Happened"], "- Strong data center demand\n- Raised guidance")

    def test_write_excel(self):
        summary = QuarterSummary(
            company_name="Nvidia",
            quarter="FY2025-Q2",
            what_happened=["Strong data center demand", "Raised guidance"],
            positives=["Blackwell ramp", "Margin recovery"],
            negatives=["China restrictions"],
            confidence="High",
        )
        with TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "summary.xlsx"
            write_excel([summary], output_path)
            workbook = load_workbook(output_path)
            worksheet = workbook["Nvidia"]
            self.assertEqual(worksheet["A1"].value, "Summary Type")
            self.assertEqual(worksheet["D2"].value, "- Strong data center demand\n- Raised guidance")

    def test_write_excel_creates_one_sheet_per_company(self):
        nvidia = QuarterSummary(
            company_name="Nvidia",
            quarter="FY2025-Q2",
            what_happened=["Strong data center demand"],
            positives=["Blackwell ramp"],
            negatives=["China restrictions"],
            confidence="High",
        )
        amazon = QuarterSummary(
            company_name="Amazon",
            quarter="FY2025-Q2",
            what_happened=["AWS growth improved"],
            positives=["Retail margin expansion"],
            negatives=["Capex pressure"],
            confidence="Medium",
        )
        with TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "summary.xlsx"
            write_excel([nvidia, amazon], output_path)
            workbook = load_workbook(output_path)
            self.assertEqual(workbook.sheetnames, ["Nvidia", "Amazon"])
            self.assertEqual(workbook["Nvidia"]["B2"].value, "Nvidia")
            self.assertEqual(workbook["Amazon"]["B2"].value, "Amazon")


if __name__ == "__main__":
    unittest.main()
