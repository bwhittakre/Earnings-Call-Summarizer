"""Tests for quarter registry skip helpers."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
