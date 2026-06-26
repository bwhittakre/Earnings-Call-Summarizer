import unittest

from src.ingest.call_date import (
    extract_call_date,
    format_call_date,
    is_valid_call_date_format,
    resolve_call_date,
)
from datetime import date


class CallDateTestCase(unittest.TestCase):
    def test_format_call_date(self):
        self.assertEqual(format_call_date(date(2025, 7, 31)), "(07,31,2025)")

    def test_extract_call_date_from_numeric_disclaimer(self):
        transcript = (
            "Our comments reflect management's views as of today, 07/31/2025 only "
            "and will include forward looking statements."
        )
        self.assertEqual(extract_call_date(transcript), "(07,31,2025)")

    def test_extract_call_date_from_named_disclaimer(self):
        transcript = (
            "All our statements are made as of today, August 28, 2024 based on "
            "information currently available to us."
        )
        self.assertEqual(extract_call_date(transcript), "(08,28,2024)")

    def test_resolve_call_date_prefers_transcript_extraction(self):
        transcript = (
            "Our comments reflect management's views as of today, 07/31/2025 only."
        )
        resolved = resolve_call_date(transcript, "(01,01,2020)")
        self.assertEqual(resolved, "(07,31,2025)")

    def test_resolve_call_date_uses_llm_fallback(self):
        resolved = resolve_call_date("No date in this transcript.", "(08,28,2024)")
        self.assertEqual(resolved, "(08,28,2024)")

    def test_is_valid_call_date_format(self):
        self.assertTrue(is_valid_call_date_format("(07,31,2025)"))
        self.assertFalse(is_valid_call_date_format("07/31/2025"))


if __name__ == "__main__":
    unittest.main()
