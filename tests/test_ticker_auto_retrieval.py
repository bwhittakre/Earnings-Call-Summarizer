import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from src.ingest.edgar.cik_lookup import (
    resolve_companies_list,
    resolve_company_identifier,
)
from src.ingest.edgar.fiscal_profile import bootstrap_fiscal_profile
from src.market.fiscal_resolver import expected_period_end_date

FIXTURES = Path(__file__).parent / "fixtures" / "edgar"


class FakeTickerFetcher:
    def __init__(self) -> None:
        self.payload = {
            "0": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
            "1": {"cik_str": 1018724, "ticker": "AMZN", "title": "AMAZON COM INC"},
        }

    def __call__(self, url: str) -> dict:
        return self.payload


class CompanyResolutionTestCase(unittest.TestCase):
    def test_resolve_ticker(self):
        ticker, cik, title = resolve_company_identifier(
            "MSFT",
            fetcher=FakeTickerFetcher(),
        )
        self.assertEqual(ticker, "MSFT")
        self.assertEqual(cik, 789019)
        self.assertIn("MICROSOFT", title.upper())

    def test_resolve_company_name(self):
        ticker, cik, title = resolve_company_identifier(
            "Microsoft",
            fetcher=FakeTickerFetcher(),
        )
        self.assertEqual(ticker, "MSFT")
        self.assertEqual(cik, 789019)

    def test_resolve_companies_list(self):
        resolved = resolve_companies_list(
            "Microsoft,AMZN",
            fetcher=FakeTickerFetcher(),
        )
        self.assertEqual([entry[0] for entry in resolved], ["MSFT", "AMZN"])


class FiscalProfileTestCase(unittest.TestCase):
    def test_bootstrap_msft_profile(self):
        submissions = json.loads(
            (FIXTURES / "msft_submissions.json").read_text(encoding="utf-8")
        )
        profile = bootstrap_fiscal_profile("MSFT", "Microsoft", submissions)
        self.assertEqual(profile.calendar_type, "offset_fiscal")
        self.assertEqual(profile.fiscal_year_end, "0630")
        self.assertIn("FY2025-Q1", profile.quarter_ends)

    def test_msft_fy2025_q1_period_end(self):
        submissions = json.loads(
            (FIXTURES / "msft_submissions.json").read_text(encoding="utf-8")
        )
        profile = bootstrap_fiscal_profile("MSFT", "Microsoft", submissions)
        resolved = expected_period_end_date(
            "MSFT",
            "FY2025-Q1",
            fiscal_profile=profile,
        )
        self.assertEqual(resolved, date(2024, 9, 30))


if __name__ == "__main__":
    unittest.main()
