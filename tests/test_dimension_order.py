"""Tests for thematic dimension ordering (Option B default)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

from dimension_order import (  # noqa: E402
    DEFAULT_PRESET,
    apply_dimension_group_column,
    dimension_display_order,
    dimension_group,
    prepare_consolidated_panel,
    sort_panel_by_dimension,
)


class DimensionOrderTests(unittest.TestCase):
    def test_default_preset_is_fundamentals_context(self):
        self.assertEqual(DEFAULT_PRESET, "fundamentals_context")

    def test_fundamentals_context_order_not_alphabetical(self):
        order = dimension_display_order("fundamentals_context")
        self.assertEqual(order[0], "demand")
        self.assertEqual(order[4], "guidance")
        self.assertEqual(order[5], "management_confidence")
        self.assertNotEqual(list(order), sorted(order))

    def test_dimension_group_mapping(self):
        self.assertEqual(dimension_group("demand"), "fundamentals")
        self.assertEqual(dimension_group("guidance"), "fundamentals")
        self.assertEqual(dimension_group("management_confidence"), "narrative_context")
        self.assertEqual(dimension_group("macro_regulatory_risk"), "narrative_context")

    def test_sort_panel_by_dimension_within_quarter(self):
        df = pd.DataFrame(
            {
                "ticker": ["AMZN"] * 8,
                "fiscal_period": ["FY2025-Q1"] * 8,
                "period_end_date": ["2025-03-31"] * 8,
                "dimension": [
                    "macro_regulatory_risk",
                    "capital_allocation",
                    "demand",
                    "management_confidence",
                    "margins",
                    "competitive_position",
                    "earnings_power",
                    "guidance",
                ],
            }
        )
        sorted_df = sort_panel_by_dimension(df)
        self.assertEqual(sorted_df["dimension"].tolist(), list(dimension_display_order()))

    def test_prepare_consolidated_panel_adds_group_column(self):
        df = pd.DataFrame(
            {
                "ticker": ["MSFT", "MSFT"],
                "fiscal_period": ["FY2025-Q1", "FY2025-Q1"],
                "dimension": ["demand", "management_confidence"],
            }
        )
        out = prepare_consolidated_panel(df)
        self.assertIn("dimension_group", out.columns)
        self.assertEqual(out.iloc[0]["dimension_group"], "fundamentals")
        self.assertEqual(out.iloc[1]["dimension_group"], "narrative_context")

    def test_all_presets_have_eight_unique_dimensions(self):
        from dimension_order import ORDER_PRESETS
        from dimension_scorer import ALL_DIMENSIONS

        for name, order in ORDER_PRESETS.items():
            self.assertEqual(len(order), len(ALL_DIMENSIONS), msg=name)
            self.assertEqual(set(order), set(ALL_DIMENSIONS), msg=name)


    def test_insert_dimension_group_header_rows(self):
        from dimension_order import insert_dimension_group_header_rows, prepare_consolidated_panel

        df = prepare_consolidated_panel(
            pd.DataFrame(
                {
                    "ticker": ["AMZN"] * 4,
                    "fiscal_period": ["FY2025-Q1"] * 4,
                    "dimension": [
                        "demand",
                        "guidance",
                        "management_confidence",
                        "macro_regulatory_risk",
                    ],
                }
            )
        )
        expanded, headers = insert_dimension_group_header_rows(df)
        self.assertEqual(len(expanded), len(df) + 2)
        self.assertEqual(len(headers), 2)
        self.assertEqual(expanded.iloc[headers[0]]["dimension"], "Fundamentals")
        self.assertEqual(expanded.iloc[headers[1]]["dimension"], "Narrative context")


if __name__ == "__main__":
    unittest.main()
