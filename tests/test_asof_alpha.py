"""Tests for as-of / event forward-return labels (multi-horizon)."""
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
    HORIZON_WINDOWS,
    apply_asof_alpha_labels,
    apply_asof_multi_horizon_labels,
    apply_event_multi_horizon_labels,
    apply_multi_horizon_alpha_labels,
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
        with tempfile.TemporaryDirectory():
            ticker = "ZZZTEST"
            ret = pd.DataFrame(
                {
                    "date_of_data": pd.date_range("2025-05-09", periods=100, freq="D"),
                    "specific_return": [0.1] * 100,
                }
            )
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

            path.unlink(missing_ok=True)

    def test_label_column_sets_default_covers_all_horizons(self):
        n_horizons = len(HORIZON_WINDOWS)
        self.assertEqual(len(label_column_sets("event")), n_horizons * 3)
        self.assertEqual(len(label_column_sets("asof")), n_horizons * 3)
        self.assertEqual(len(label_column_sets("both")), n_horizons * 6)

    def test_label_column_sets_horizon_filter(self):
        self.assertEqual(len(label_column_sets("event", horizons=["0_90"])), 3)
        self.assertEqual(
            label_column_sets("asof", horizons=["0_14"]),
            ["alpha_spec_asof_0_14", "alpha_spec_asof_0_14_z", "alpha_spec_asof_0_14_complete"],
        )

    def test_multi_horizon_windows_tile_without_gap_or_overlap(self):
        """The T+7-T+21 / T+22-T+42 / T+43-T+63 windows should compound to the
        same total return as the single combined T+7-T+63 window (they tile
        the same date range with the same exclusive-start/inclusive-end rule)."""
        ticker = "ZZZTILE"
        ret = pd.DataFrame(
            {
                "date_of_data": pd.date_range("2025-01-01", periods=120, freq="D"),
                "specific_return": [0.2] * 120,
            }
        )
        path = save_specific_returns(ticker, ret)
        try:
            panel = pd.DataFrame({"ticker": [ticker], "investable_as_of_date": ["2025-01-05"]})
            out = apply_asof_multi_horizon_labels(panel, fetch_if_missing=False)
            r1 = out.iloc[0]["alpha_spec_asof_0_14"]
            r2 = out.iloc[0]["alpha_spec_asof_14_35"]
            r3 = out.iloc[0]["alpha_spec_asof_35_56"]
            combined = out.iloc[0]["alpha_spec_asof_0_56"]
            chained = (1.0 + r1) * (1.0 + r2) * (1.0 + r3) - 1.0
            self.assertAlmostEqual(chained, combined, places=8)
        finally:
            path.unlink(missing_ok=True)

    def test_apply_multi_horizon_alpha_labels_generic_anchor(self):
        ticker = "ZZZGEN"
        ret = pd.DataFrame(
            {
                "date_of_data": pd.date_range("2025-02-01", periods=100, freq="D"),
                "specific_return": [0.05] * 100,
            }
        )
        path = save_specific_returns(ticker, ret)
        try:
            panel = pd.DataFrame({"ticker": [ticker], "my_anchor": ["2025-02-05"]})
            out = apply_multi_horizon_alpha_labels(
                panel,
                anchor_col="my_anchor",
                prefix="custom_alpha",
                windows=(("0_14", 0, 14, "test"),),
                fetch_if_missing=False,
            )
            self.assertIn("custom_alpha_0_14", out.columns)
            self.assertTrue(bool(out.iloc[0]["custom_alpha_0_14_complete"]))
        finally:
            path.unlink(missing_ok=True)

    def test_apply_event_multi_horizon_labels_computes_model_date_offline(self):
        ticker = "ZZZEVT"
        ret = pd.DataFrame(
            {
                "date_of_data": pd.date_range("2025-01-01", periods=150, freq="D"),
                "specific_return": [0.1] * 150,
            }
        )
        path = save_specific_returns(ticker, ret)
        try:
            # model_date_from("2025-01-01") = 2025-01-08 (Wed + 7d, no weekend roll).
            panel = pd.DataFrame({"ticker": [ticker], "earnings_date": ["2025-01-01"]})
            out = apply_event_multi_horizon_labels(panel, fetch_if_missing=False, validate_legacy=False)
            self.assertIn("alpha_spec_0_14", out.columns)
            self.assertTrue(bool(out.iloc[0]["alpha_spec_0_14_complete"]))
            # specific_return is in percent (compound_specific_return divides by 100).
            self.assertAlmostEqual(out.iloc[0]["alpha_spec_0_14"], (1.001**14) - 1.0, places=8)
        finally:
            path.unlink(missing_ok=True)

    def test_apply_event_multi_horizon_labels_preserves_legacy_on_disk_value(self):
        """The on-disk (Snowflake-sourced) alpha_spec_0_90 triple must survive
        unchanged even though this function recomputes it offline to validate."""
        ticker = "ZZZLEGACY"
        ret = pd.DataFrame(
            {
                "date_of_data": pd.date_range("2025-01-01", periods=150, freq="D"),
                "specific_return": [0.1] * 150,
            }
        )
        path = save_specific_returns(ticker, ret)
        try:
            panel = pd.DataFrame(
                {
                    "ticker": [ticker],
                    "earnings_date": ["2025-01-01"],
                    # Deliberately wrong "on-disk" value to prove it's preserved, not overwritten.
                    "alpha_spec_0_90": [999.0],
                    "alpha_spec_0_90_z": [0.0],
                    "alpha_spec_0_90_complete": [True],
                }
            )
            out = apply_event_multi_horizon_labels(panel, fetch_if_missing=False, validate_legacy=True)
            self.assertEqual(out.iloc[0]["alpha_spec_0_90"], 999.0)
            self.assertNotIn("_model_date_offline", out.columns)
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
