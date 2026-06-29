import unittest

from src.market.quarter_labels import prior_quarter_labels


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

    def test_prior_quarter_labels_forty_quarters_span_ten_years(self):
        labels = prior_quarter_labels("2025-Q4", count=40)
        self.assertEqual(len(labels), 40)
        self.assertEqual(labels[0], "2015-Q4")
        self.assertEqual(labels[-1], "2025-Q3")

    def test_prior_quarter_labels_fiscal_forty_quarters(self):
        labels = prior_quarter_labels("FY2026-Q2", count=40)
        self.assertEqual(len(labels), 40)
        self.assertEqual(labels[0], "FY2016-Q2")
        self.assertEqual(labels[-1], "FY2026-Q1")


if __name__ == "__main__":
    unittest.main()
