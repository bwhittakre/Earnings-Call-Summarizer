import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from openpyxl import load_workbook

from src.export.confidence_reference_key import (
    REFERENCE_KEY_TITLE,
    load_reference_key_text,
)
from src.export.csv_writer import (
    EXCEL_COLUMN_WIDTHS,
    EXCEL_MAX_ROW_HEIGHT,
    format_analysis_bullets,
    format_bullets,
    format_list,
    format_quarter_cell,
    format_what_happened,
    max_lines_at_max_height,
    min_column_width_for_text,
    summary_to_excel_row,
    summary_to_row,
    write_excel,
)
from src.ingest.loader import (
    assign_quarters,
    dry_run_report,
    load_transcripts,
    normalize_quarter_label,
    parse_quarter_from_filename,
    resolve_transcript_files,
)
from src.schemas.models import EvidenceClaim, QuarterSummary

SAMPLE_ANALYSIS = [
    EvidenceClaim(
        claim="+20: Raised outlook supports next-quarter momentum",
        excerpt="We are raising full-year revenue guidance across every segment.",
    )
]


def _sample_summary(**overrides) -> QuarterSummary:
    payload = {
        "company_name": "Nvidia",
        "quarter": "FY2025-Q2",
        "what_happened": ["Strong data center demand", "Raised guidance"],
        "positives": ["Blackwell ramp", "Margin recovery"],
        "negatives": ["China restrictions"],
        "confidence_score": 72,
        "transcript_only_confidence_score": 72,
        "analysis": list(SAMPLE_ANALYSIS),
    }
    payload.update(overrides)
    return QuarterSummary(**payload)


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
        summary = _sample_summary(company_name="Microsoft", quarter="2024-Q3")
        row = summary_to_row(summary)
        self.assertEqual(row["what_happened"], "Strong data center demand & Raised guidance")
        self.assertEqual(row["positives"], "Blackwell ramp, Margin recovery")
        self.assertEqual(row["confidence_score"], "72")
        self.assertIn("We are raising full-year revenue guidance", row["analysis"])
        self.assertEqual(format_what_happened(["A", "B"]), "A & B")
        self.assertEqual(format_list(["X", "Y"]), "X, Y")
        self.assertEqual(format_bullets(["X", "Y"]), "- X\n- Y")

    def test_analysis_bullet_formatting_includes_excerpt(self):
        formatted = format_analysis_bullets(SAMPLE_ANALYSIS)
        self.assertIn("+20: Raised outlook supports next-quarter momentum", formatted)
        self.assertIn('"We are raising full-year revenue guidance across every segment."', formatted)
        self.assertIn(" — ", formatted)

    def test_min_column_width_for_text_expands_for_long_content(self):
        short_text = "Brief analysis point."
        long_text = "\n".join(
            f'• +10: Factor {index} — "{("detail " * 30).strip()}"'
            for index in range(15)
        )
        max_lines = max_lines_at_max_height()
        short_width = min_column_width_for_text(short_text, max_lines)
        long_width = min_column_width_for_text(long_text, max_lines)
        self.assertLess(short_width, long_width)
        self.assertGreater(long_width, EXCEL_COLUMN_WIDTHS["Analysis"])

    def test_write_excel_widens_analysis_column_for_long_analysis(self):
        long_analysis = [
            EvidenceClaim(
                claim=f"+{index}: Industry driver {index}",
                excerpt=("Management discussed metric with detailed commentary " + ("data " * 40)).strip(),
            )
            for index in range(1, 16)
        ]
        summary = _sample_summary(analysis=long_analysis)
        with TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "summary.xlsx"
            write_excel([summary], output_path)
            workbook = load_workbook(output_path)
            worksheet = workbook["Nvidia"]
            self.assertGreater(
                worksheet.column_dimensions["I"].width,
                EXCEL_COLUMN_WIDTHS["Analysis"],
            )
            self.assertLessEqual(worksheet.row_dimensions[2].height, EXCEL_MAX_ROW_HEIGHT)

    def test_excel_row_formatting(self):
        summary = _sample_summary()
        row = summary_to_excel_row(summary)
        self.assertEqual(row["Summary Type"], "Quarter")
        self.assertEqual(row["What Happened"], "- Strong data center demand\n- Raised guidance")
        self.assertEqual(row["Confidence Score"], "72")
        self.assertEqual(row["Document-Only Score"], "72")
        self.assertIn('"We are raising full-year revenue guidance across every segment."', row["Analysis"])

    def test_write_excel(self):
        summary = _sample_summary(call_date="(08,28,2024)")
        with TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "summary.xlsx"
            write_excel([summary], output_path)
            workbook = load_workbook(output_path)
            worksheet = workbook["Nvidia"]
            self.assertEqual(worksheet["A1"].value, "Summary Type")
            self.assertEqual(worksheet["G1"].value, "Document-Only Score")
            self.assertEqual(worksheet["H1"].value, "Confidence Score")
            self.assertEqual(worksheet["I1"].value, "Analysis")
            self.assertEqual(worksheet["D2"].value, "- Strong data center demand\n- Raised guidance")
            self.assertEqual(worksheet["G2"].value, "72")
            self.assertEqual(worksheet["H2"].value, "72")
            self.assertEqual(
                worksheet["C2"].value,
                "FY2025-Q2\nCall Date: (08,28,2024)",
            )
            self.assertEqual(worksheet["K1"].value, REFERENCE_KEY_TITLE)
            self.assertIn(
                "sum of all Analysis bullet weights",
                str(worksheet["K2"].value),
            )
            self.assertEqual(worksheet.auto_filter.ref, "A1:I2")

    def test_load_reference_key_text(self):
        text = load_reference_key_text()
        self.assertIn("Score interpretation bands", text)
        self.assertIn("no fixed maximum", text)
        self.assertIn("Strong stock-moving drivers: ±20 to ±25", text)
        self.assertIn("NEXT QUARTER ONLY", text)
        self.assertIn("eight fiscal quarter-ends spanning approximately two years", text)
        self.assertGreater(len(text), 100)

    def test_write_excel_creates_one_sheet_per_company(self):
        nvidia = _sample_summary()
        amazon = _sample_summary(
            company_name="Amazon",
            what_happened=["AWS growth improved"],
            positives=["Retail margin expansion"],
            negatives=["Capex pressure"],
            confidence_score=-15,
        )
        with TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / "summary.xlsx"
            write_excel([nvidia, amazon], output_path)
            workbook = load_workbook(output_path)
            self.assertEqual(workbook.sheetnames, ["Nvidia", "Amazon"])
            self.assertEqual(workbook["Nvidia"]["B2"].value, "Nvidia")
            self.assertEqual(workbook["Amazon"]["B2"].value, "Amazon")
            self.assertEqual(workbook["Nvidia"]["K1"].value, REFERENCE_KEY_TITLE)
            self.assertEqual(workbook["Amazon"]["K1"].value, REFERENCE_KEY_TITLE)

    def test_load_single_transcript_file(self):
        transcript_path = (
            Path(__file__).resolve().parent.parent
            / "data"
            / "transcripts"
            / "nvidia"
            / "FY2025-Q2.txt"
        )
        if not transcript_path.exists():
            self.skipTest("Nvidia FY2025-Q2 transcript fixture not present")

        loaded = load_transcripts(transcript_path)
        self.assertEqual(list(loaded.transcripts.keys()), ["FY2025-Q2"])
        self.assertGreater(len(loaded.transcripts["FY2025-Q2"]), 1000)

    def test_resolve_quarter_filter_from_folder(self):
        source = (
            Path(__file__).resolve().parent.parent
            / "data"
            / "transcripts"
            / "nvidia"
            / "FY2025-Q2.txt"
        )
        if not source.is_file():
            self.skipTest("Nvidia FY2025-Q2 transcript fixture not present")

        with TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "FY2025-Q2.txt").write_text(
                source.read_text(encoding="utf-8", errors="replace"),
                encoding="utf-8",
            )
            assigned = resolve_transcript_files(folder, quarter="FY2025-Q2")
            self.assertEqual(len(assigned), 1)
            self.assertEqual(assigned[0].quarter, "FY2025-Q2")
            self.assertEqual(assigned[0].path.name, "FY2025-Q2.txt")

    def test_normalize_quarter_label(self):
        self.assertEqual(normalize_quarter_label("FY2025-Q2"), "FY2025-Q2")
        self.assertEqual(normalize_quarter_label("2025-Q2"), "2025-Q2")

    def test_dry_run_single_file(self):
        transcript_path = (
            Path(__file__).resolve().parent.parent
            / "data"
            / "transcripts"
            / "nvidia"
            / "FY2025-Q2.txt"
        )
        if not transcript_path.exists():
            self.skipTest("Nvidia FY2025-Q2 transcript fixture not present")

        report = dry_run_report(transcript_path)
        self.assertIn("Validation: OK", report)
        self.assertIn("auto-detect from transcript", report)
        self.assertIn("FY2025-Q2.txt", report)


if __name__ == "__main__":
    unittest.main()
