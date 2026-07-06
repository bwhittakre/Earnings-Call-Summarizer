import unittest
from datetime import date

from src.ingest.edgar.fiscal_profile import FiscalProfile
from src.ingest.edgar.resolver import expand_fetch_quarters
from src.market.quarter_end_mode import (
    build_quarter_end_run,
    parse_quarter_end_anchor,
    resolve_quarter_label_for_date,
)

MSFT_PROFILE = FiscalProfile(
    ticker="MSFT",
    company_name="Microsoft",
    fiscal_year_end="0630",
    calendar_type="offset_fiscal",
    fye_month=6,
    fye_day=30,
    quarter_ends={},
)


class QuarterEndModeTestCase(unittest.TestCase):
    def test_parse_quarter_end_anchor(self):
        self.assertEqual(parse_quarter_end_anchor("2025-06-30"), date(2025, 6, 30))

    def test_parse_invalid_anchor_raises(self):
        with self.assertRaises(Exception):
            parse_quarter_end_anchor("30/06/2025")

    def test_msft_jun_30_2025_resolves_fy2025_q4(self):
        label = resolve_quarter_label_for_date(
            "MSFT",
            date(2025, 6, 30),
            fiscal_profile=MSFT_PROFILE,
        )
        self.assertEqual(label, "FY2025-Q4")

    def test_amzn_jun_30_2025_resolves_fy2026_q2(self):
        label = resolve_quarter_label_for_date("AMZN", date(2025, 6, 30))
        self.assertEqual(label, "FY2026-Q2")

    def test_build_quarter_end_run_maps_companies(self):
        run = build_quarter_end_run(
            ["MSFT", "AMZN"],
            date(2025, 6, 30),
            fiscal_profiles={"MSFT": MSFT_PROFILE},
        )
        self.assertEqual(run.anchor_date, date(2025, 6, 30))
        self.assertEqual(run.company_quarters["MSFT"], "FY2025-Q4")
        self.assertEqual(run.company_quarters["AMZN"], "FY2026-Q2")
        self.assertEqual(
            run.date_overrides()["FY2025-Q4"],
            date(2025, 6, 30),
        )


class Q4SiblingFetchTestCase(unittest.TestCase):
    def test_expand_fetch_quarters_q4_includes_siblings(self):
        self.assertEqual(
            expand_fetch_quarters("FY2025-Q4"),
            ["FY2025-Q1", "FY2025-Q2", "FY2025-Q3", "FY2025-Q4"],
        )

    def test_expand_fetch_quarters_q2_is_single(self):
        self.assertEqual(expand_fetch_quarters("FY2026-Q2"), ["FY2026-Q2"])


if __name__ == "__main__":
    unittest.main()
