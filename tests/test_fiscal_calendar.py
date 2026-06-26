import unittest
from datetime import date
from pathlib import Path

from src.market.fiscal_calendar import (
    parse_quarter_end_dates_override,
    resolve_quarter_end_date,
)


class FiscalCalendarTestCase(unittest.TestCase):
    def test_amazon_calendar_fiscal_quarter_end(self):
        resolved = resolve_quarter_end_date("AMZN", "FY2025-Q2")
        self.assertEqual(resolved, date(2025, 6, 30))

    def test_nvidia_fiscal_quarter_end(self):
        resolved = resolve_quarter_end_date("NVDA", "FY2025-Q2")
        self.assertEqual(resolved.weekday(), 6)
        self.assertEqual(resolved.month, 7)
        self.assertEqual(resolved.year, 2024)

    def test_cli_override_wins(self):
        overrides = parse_quarter_end_dates_override("FY2025-Q2:2024-07-28")
        resolved = resolve_quarter_end_date(
            "NVDA",
            "FY2025-Q2",
            overrides=overrides,
        )
        self.assertEqual(resolved, date(2024, 7, 28))

    def test_missing_ticker_raises(self):
        with self.assertRaises(Exception):
            resolve_quarter_end_date(
                "ZZZZ",
                "FY2025-Q2",
                calendars_path=Path(__file__).resolve().parent.parent
                / "config"
                / "fiscal_calendars.yaml",
            )


if __name__ == "__main__":
    unittest.main()
