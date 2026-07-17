"""Tests for as-of forward-return labels."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

from asof_alpha import (  # noqa: E402
    apply_asof_alpha_labels,
    compound_specific_return,
    label_column_sets,
    save_specific_returns,
)


class AsofAlphaTests(unittest.TestCase):
    def test_compound_specific_return_window(self):
        ret = pd.DataFrame(
            {
                "date_of_data": pd.to_datetime(
                    ["2025-05-08", "2025-05-09", "2025-05-10", "2025-08-06"]
                ),
                "specific_return": [1.0, 1.0, 1.0, 0.0],
            }
        )
        # Exclusive start 2025-05-08 → days after start: 05-09, 05-10, 08-06
        val, ok = compound_specific_return(ret, "2025-05-08", "2025-08-06")
        self.assertTrue(ok)
        self.assertAlmostEqual(val, (1.01**2) * 1.0 - 1.0, places=8)

    def test_apply_asof_alpha_from_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Point company_artifact at a temp tree by monkeypatching via save path
            ticker = "ZZZTEST"
            ret = pd.DataFrame(
                {
                    "date_of_data": pd.date_range("2025-05-09", periods=100, freq="D"),
                    "specific_return": [0.1] * 100,
                }
            )
            # Save using real output path helper under Structured Narrative/output
            path = save_specific_returns(ticker, ret)
            self.assertTrue(path.exists())

            panel = pd.DataFrame(
                {
                    "ticker": [ticker, ticker],
                    "investable_as_of_date": ["2025-05-08", "2025-05-08"],
                    "dimension": ["demand", "guidance"],
                }
            )
            out = apply_asof_alpha_labels(panel, fetch_if_missing=False)
            self.assertTrue(bool(out.iloc[0]["alpha_spec_asof_0_90_complete"]))
            self.assertIsNotNone(out.iloc[0]["alpha_spec_asof_0_90"])

            # cleanup cached returns
            path.unlink(missing_ok=True)

    def test_label_column_sets(self):
        self.assertEqual(len(label_column_sets("event")), 3)
        self.assertEqual(len(label_column_sets("asof")), 3)
        self.assertEqual(len(label_column_sets("both")), 6)


if __name__ == "__main__":
    unittest.main()
