import unittest
from datetime import date
from pathlib import Path

from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH
from src.market.quarter_labels import (
    prior_quarter_labels,
    prior_quarter_labels_for_price_lookup,
)


class QuarterLabelsTestCase(unittest.TestCase):
    def test_prior_quarter_labels_from_fy2026_q2(self):
        self.assertEqual(
            prior_quarter_labels("FY2026-Q2"),
            ["FY2025-Q2", "FY2025-Q3", "FY2025-Q4", "FY2026-Q1"],
        )

    def test_prior_quarter_labels_calendar(self):
        self.assertEqual(
            prior_quarter_labels("2025-Q1"),
            ["2024-Q1", "2024-Q2", "2024-Q3", "2024-Q4"],
        )

    def test_prior_quarter_labels_for_price_lookup_fy2026_q1(self):
        labels = prior_quarter_labels_for_price_lookup(
            "FY2026-Q1",
            date(2025, 3, 31),
            "AMZN",
            calendars_path=DEFAULT_FISCAL_CALENDARS_PATH,
        )
        self.assertEqual(
            labels,
            ["FY2024-Q2", "FY2024-Q3", "FY2024-Q4", "FY2025-Q1"],
        )

    def test_prior_quarter_labels_for_price_lookup_fy2026_q2(self):
        overrides = {"FY2026-Q1": date(2025, 3, 31), "FY2026-Q2": date(2025, 6, 30)}
        labels = prior_quarter_labels_for_price_lookup(
            "FY2026-Q2",
            date(2025, 6, 30),
            "AMZN",
            calendars_path=DEFAULT_FISCAL_CALENDARS_PATH,
            overrides=overrides,
        )
        self.assertEqual(
            labels,
            ["FY2024-Q4", "FY2025-Q1", "FY2025-Q2", "FY2026-Q1"],
        )


if __name__ == "__main__":
    unittest.main()
