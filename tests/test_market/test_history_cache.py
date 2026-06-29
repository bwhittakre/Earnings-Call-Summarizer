import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from src.market.history_cache import batch_history_fetcher, clear_history_cache


class HistoryCacheTestCase(unittest.TestCase):
    def test_cached_fetcher_reuses_history_rows(self):
        clear_history_cache()
        rows = [(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 101.0)]
        fetcher = batch_history_fetcher()

        with patch(
            "src.market.history_cache._default_history_fetcher",
            return_value=rows,
        ) as mock_fetch:
            first = fetcher("NVDA", date(2024, 1, 1), date(2024, 1, 10))
            second = fetcher("NVDA", date(2024, 1, 1), date(2024, 1, 10))

        self.assertEqual(first, rows)
        self.assertEqual(second, rows)
        mock_fetch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
