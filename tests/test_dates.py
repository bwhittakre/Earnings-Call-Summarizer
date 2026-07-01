import unittest
from datetime import date

from src.ingest.dates import (
    format_as_of_date,
    is_valid_as_of_date_format,
    parse_as_of_date_format,
    resolve_as_of_date_text,
    resolve_as_of_date_value,
)


class DatesTestCase(unittest.TestCase):
    def test_format_as_of_date(self):
        self.assertEqual(format_as_of_date(date(2026, 2, 5)), "(02,05,2026)")

    def test_is_valid_as_of_date_format(self):
        self.assertTrue(is_valid_as_of_date_format("(08,28,2024)"))
        self.assertFalse(is_valid_as_of_date_format("08/28/2024"))
        self.assertFalse(is_valid_as_of_date_format("08/28/2024"))

    def test_parse_as_of_date_format(self):
        self.assertEqual(parse_as_of_date_format("(02,05,2026)"), date(2026, 2, 5))
        self.assertIsNone(parse_as_of_date_format("invalid"))

    def test_resolve_as_of_date_text_prefers_manifest(self):
        self.assertEqual(
            resolve_as_of_date_text("(08,28,2024)", "(01,01,2020)"),
            "(08,28,2024)",
        )

    def test_resolve_as_of_date_text_uses_llm_fallback(self):
        self.assertEqual(
            resolve_as_of_date_text(None, "(08,28,2024)"),
            "(08,28,2024)",
        )

    def test_resolve_as_of_date_value_optional(self):
        self.assertIsNone(resolve_as_of_date_value(None))

    def test_resolve_as_of_date_value_required_raises(self):
        with self.assertRaises(ValueError):
            resolve_as_of_date_value(None, required=True)

    def test_resolve_as_of_date_value_parses_manifest(self):
        self.assertEqual(
            resolve_as_of_date_value("(08,28,2024)"),
            date(2024, 8, 28),
        )


if __name__ == "__main__":
    unittest.main()
