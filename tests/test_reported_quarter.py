import unittest
from pathlib import Path

from src.ingest.reported_quarter import extract_reported_quarter, resolve_reported_quarter


AMAZON_OPENING = (
    "Hello, and welcome to our Q4 2025 financial results conference call. "
    "Our comments reflect management's views as of today, February 5, 2026, only."
)


class ReportedQuarterTestCase(unittest.TestCase):
    def test_extract_amazon_q4_2025(self):
        self.assertEqual(extract_reported_quarter(AMAZON_OPENING), "2025-Q4")

    def test_resolve_uses_cli_override(self):
        self.assertEqual(
            resolve_reported_quarter("no quarter here", cli_override="FY2025-Q2"),
            "FY2025-Q2",
        )

    def test_extract_from_amazon_transcript_file(self):
        transcript_path = (
            Path(__file__).resolve().parent.parent
            / "data"
            / "transcripts"
            / "amazon"
            / "FY2026-Q4.txt"
        )
        if not transcript_path.exists():
            self.skipTest("Amazon FY2026-Q4 transcript fixture not present")
        text = transcript_path.read_text(encoding="utf-8", errors="replace")
        self.assertEqual(extract_reported_quarter(text), "2025-Q4")


if __name__ == "__main__":
    unittest.main()
