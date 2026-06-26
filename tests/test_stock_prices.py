import unittest
from datetime import date

from src.market.stock_prices import fetch_quarter_end_prices


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


if __name__ == "__main__":
    unittest.main()
