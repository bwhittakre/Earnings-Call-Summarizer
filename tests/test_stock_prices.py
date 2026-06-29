import unittest
from datetime import date

from src.market.fiscal_calendar import resolve_quarter_end_date
from src.market.quarter_labels import prior_quarter_labels
from src.market.stock_prices import StockPriceError, fetch_quarter_end_prices


class StockPricesTestCase(unittest.TestCase):
    def test_fetch_quarter_end_prices_uses_last_trading_day(self):
        def fake_fetcher(ticker: str, start: date, end: date):
            self.assertEqual(ticker, "NVDA")
            return [
                (date(2024, 7, 25), 100.0),
                (date(2024, 7, 26), 101.5),
            ]

        prices = fetch_quarter_end_prices(
            "NVDA",
            {"FY2025-Q2": date(2024, 7, 28)},
            ordered_labels=["FY2025-Q2"],
            fetcher=fake_fetcher,
            as_of_date=date(2024, 7, 28),
        )
        self.assertEqual(len(prices), 1)
        self.assertEqual(prices[0].price_date, date(2024, 7, 26))
        self.assertEqual(prices[0].adjusted_close, 101.5)
        self.assertIn("$101.50", prices[0].format_line())

    def test_fetch_caps_at_call_date(self):
        def fake_fetcher(ticker: str, start: date, end: date):
            self.assertEqual(end, date(2025, 9, 30))
            return [(date(2025, 9, 30), 180.0)]

        prices = fetch_quarter_end_prices(
            "AMZN",
            {"2025-Q3": date(2025, 9, 30)},
            ordered_labels=["2025-Q3"],
            fetcher=fake_fetcher,
            as_of_date=date(2026, 2, 5),
        )
        self.assertEqual(prices[0].price_date, date(2025, 9, 30))

    def test_fetch_uses_single_batched_history_request(self):
        calls: list[tuple[str, date, date]] = []

        def fake_fetcher(ticker: str, start: date, end: date):
            calls.append((ticker, start, end))
            rows: list[tuple[date, float]] = []
            cursor = start
            while cursor <= end:
                rows.append((cursor, float(cursor.day)))
                cursor = date.fromordinal(cursor.toordinal() + 1)
            return rows

        quarter_dates = {
            "2025-Q1": date(2025, 3, 31),
            "2025-Q2": date(2025, 6, 30),
            "2025-Q3": date(2025, 9, 30),
        }
        prices = fetch_quarter_end_prices(
            "AMZN",
            quarter_dates,
            ordered_labels=["2025-Q1", "2025-Q2", "2025-Q3"],
            fetcher=fake_fetcher,
            as_of_date=date(2025, 10, 1),
        )
        self.assertEqual(len(prices), 3)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "AMZN")
        self.assertLessEqual(calls[0][1], date(2025, 3, 17))
        self.assertEqual(calls[0][2], date(2025, 9, 30))

    def test_fetch_raises_when_history_missing_for_quarter(self):
        def fake_fetcher(ticker: str, start: date, end: date):
            return []

        with self.assertRaises(StockPriceError):
            fetch_quarter_end_prices(
                "AMZN",
                {"2025-Q1": date(2025, 3, 31)},
                ordered_labels=["2025-Q1"],
                fetcher=fake_fetcher,
                as_of_date=date(2025, 4, 1),
            )


class FiscalCalendarHistoryTestCase(unittest.TestCase):
    def test_resolve_quarter_end_date_for_label_forty_quarters_back(self):
        oldest = prior_quarter_labels("FY2025-Q2", count=40)[0]
        resolved = resolve_quarter_end_date("NVDA", oldest)
        self.assertEqual(resolved.weekday(), 6)
        self.assertEqual(resolved.year, 2014)
        self.assertEqual(resolved.month, 7)


if __name__ == "__main__":
    unittest.main()
