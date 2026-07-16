"""Tests for quarter registry skip helpers and panel quant consistency."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

from quarter_registry import (  # noqa: E402
    ensure_registry,
    has_delta,
    has_dimensions,
    has_surprise,
    is_quarter_complete,
)
from quant_panel import apply_derived_features  # noqa: E402
from validate_panel_quant import validate_panel_quant  # noqa: E402


class QuarterRegistrySkipTests(unittest.TestCase):
    def test_has_layer_flags(self):
        reg = {
            "scored_quarters": {
                "FY2025-Q1": {
                    "dimensions_scored_at": "t1",
                    "delta_scored_at": "t2",
                },
                "FY2025-Q2": {
                    "dimensions_scored_at": "t1",
                    "surprise_scored_at": "t3",
                },
            }
        }
        self.assertTrue(has_dimensions(reg, "FY2025-Q1"))
        self.assertTrue(has_delta(reg, "FY2025-Q1"))
        self.assertFalse(has_surprise(reg, "FY2025-Q1"))
        self.assertFalse(is_quarter_complete(reg, "FY2025-Q1"))
        self.assertTrue(has_surprise(reg, "FY2025-Q2"))
        self.assertFalse(has_delta(reg, "FY2025-Q2"))

    def test_ensure_registry_bootstraps_from_views(self):
        msft_view = SN / "output" / "MSFT" / "json" / "dimension_view.json"
        if not msft_view.exists():
            self.skipTest("MSFT dimension_view not present")
        reg = ensure_registry("MSFT")
        self.assertTrue(reg.get("scored_quarters"))
        self.assertTrue(has_dimensions(reg, "FY2025-Q1"))


class PanelQuantTests(unittest.TestCase):
    def test_apply_derived_features_adds_divergence_flags(self):
        panel = pd.DataFrame(
            [
                {
                    "ticker": "TST",
                    "fiscal_period": "FY2025-Q1",
                    "dimension": "demand",
                    "quant_z_pit": 0.5,
                    "quant_z": 0.5,
                    "llm_level": -0.4,
                    "change_magnitude": 0.2,
                    "quant_z_delta": -0.1,
                    "surprise_magnitude": 0.6,
                    "agrees_with_quant": False,
                    "narrative_quant_gap": 0.1,
                }
            ]
        )
        out = apply_derived_features(panel)
        self.assertIn("any_quant_divergence", out.columns)
        self.assertTrue(bool(out.iloc[0]["any_quant_divergence"]))

    def test_spine_export_rules(self):
        from spine_export import panel_to_spine, validate_spine_rules

        panel = pd.DataFrame(
            [
                {
                    "ticker": "TST",
                    "fiscal_period": "FY2025-Q1",
                    "dimension": "demand",
                    "earnings_date": "2025-05-01",
                    "feature_availability_date": "2025-05-01",
                    "llm_level": 1.0,
                    "surprise_magnitude": 0.5,
                    "narrative_novelty": None,
                    "quant_z_pit": 0.2,
                    "level_evidence_supported_pct": 1.0,
                },
                {
                    "ticker": "TST",
                    "fiscal_period": "FY2025-Q1",
                    "dimension": "management_confidence",
                    "earnings_date": "2025-05-01",
                    "feature_availability_date": "2025-05-01",
                    "llm_level": 0.5,
                    "surprise_magnitude": None,
                    "narrative_novelty": 1.0,
                    "quant_z_pit": None,
                    "novelty_evidence_supported_pct": 1.0,
                },
            ]
        )
        spine = panel_to_spine(panel)
        self.assertEqual(validate_spine_rules(spine), [])

    def test_msft_panel_quant_matches_spine_if_present(self):
        panel_path = SN / "output" / "MSFT" / "csv" / "feature_panel.csv"
        if not panel_path.exists():
            self.skipTest("MSFT feature panel not present")
        errors = validate_panel_quant("MSFT")
        self.assertEqual(errors, [], msg="\n".join(errors[:5]))


if __name__ == "__main__":
    unittest.main()
