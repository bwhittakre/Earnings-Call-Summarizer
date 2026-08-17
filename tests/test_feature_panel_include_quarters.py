"""Unit coverage for quant-preface --include-quarters panel publish."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

import build_feature_panel as bfp  # noqa: E402


class FeaturePanelIncludeQuartersTests(unittest.TestCase):
    def test_prepare_level_and_delta_empty_frames(self):
        level = bfp.prepare_level(pd.DataFrame())
        delta = bfp.prepare_delta(pd.DataFrame())
        self.assertEqual(list(level.columns), bfp._LEVEL_OUT_COLS)
        self.assertEqual(list(delta.columns), bfp._DELTA_OUT_COLS)
        self.assertTrue(level.empty)
        self.assertTrue(delta.empty)

    def test_keep_quarters_unions_include_with_registry_complete(self):
        registry = {
            "prior_only_quarters": ["FY2025-Q4"],
            "scored_quarters": {
                "FY2025-Q4": {"dimensions_scored_at": "x"},
                "FY2026-Q1": {
                    "dimensions_scored_at": "x",
                    "delta_scored_at": "x",
                    "surprise_scored_at": "x",
                    "novelty_scored_at": "x",
                },
            },
        }

        with patch.object(bfp, "load_registry", return_value=registry):
            keep = bfp.resolve_panel_keep_quarters(
                include_quarters={"FY2026-Q2"},
                from_registry=True,
                ticker="MSFT",
                output_quarters=None,
            )

        self.assertEqual(keep, {"FY2026-Q1", "FY2026-Q2"})
        self.assertNotIn("FY2025-Q4", keep)

    def test_keep_quarters_scope_unions_include(self):
        keep = bfp.resolve_panel_keep_quarters(
            include_quarters={"FY2026-Q2"},
            from_registry=False,
            ticker="AMZN",
            output_quarters={"FY2024-Q1", "FY2024-Q2"},
        )
        self.assertEqual(keep, {"FY2024-Q1", "FY2024-Q2", "FY2026-Q2"})

    def test_merge_panel_keeps_quant_sparse_rows_with_full_spine(self):
        spine = pd.DataFrame(
            [
                {
                    "ticker": "MSFT",
                    "fiscal_period": "FY2026-Q2",
                    "period_end_date": "2025-12-31",
                    "dimension": "demand",
                    "as_of_date": "2026-01-28",
                    "earnings_date": "2026-01-28",
                    "model_date": None,
                    "quant_mapping": "revenue_growth",
                    "quant_family": "growth",
                    "quant_z": 0.85,
                    "quant_z_pit": 0.85,
                    "quant_z_fullsample": 0.9,
                    "quant_z_raw": 0.1,
                    "quant_quality_flags": "[]",
                    "quant_quality_ok": True,
                    "quant_guidance_revision_z_pit": None,
                    "alpha_spec_0_90": None,
                    "alpha_spec_0_90_z": None,
                    "alpha_spec_0_90_complete": None,
                }
            ]
        )
        empty_level = bfp.prepare_level(pd.DataFrame())
        empty_delta = bfp.prepare_delta(pd.DataFrame())
        empty_surprise = bfp.prepare_surprise(
            pd.DataFrame(
                columns=[
                    "ticker",
                    "fiscal_period",
                    "dimension",
                    "as_of_date",
                    "surprise_direction",
                    "surprise_magnitude",
                    "agrees_with_quant",
                    "narrative_quant_gap",
                    "rationale",
                    "n_evidence_verified",
                    "n_evidence",
                    "evidence_verified",
                ]
            )
        )
        empty_novelty = bfp.prepare_novelty(pd.DataFrame())

        with patch.object(
            bfp,
            "apply_asof_alpha_labels",
            side_effect=lambda panel, **kwargs: panel.assign(
                alpha_spec_asof_0_90=None,
                alpha_spec_asof_0_90_z=None,
                alpha_spec_asof_0_90_complete=None,
            ),
        ):
            kept = bfp.merge_panel(
                spine,
                empty_level,
                empty_delta,
                empty_surprise,
                empty_novelty,
                full_spine=True,
            )
            dropped = bfp.merge_panel(
                spine,
                empty_level,
                empty_delta,
                empty_surprise,
                empty_novelty,
                full_spine=False,
            )

        self.assertEqual(len(kept), 1)
        self.assertEqual(kept.iloc[0]["fiscal_period"], "FY2026-Q2")
        self.assertAlmostEqual(float(kept.iloc[0]["quant_z"]), 0.85)
        self.assertTrue(pd.isna(kept.iloc[0]["llm_level"]))
        self.assertTrue(dropped.empty)


if __name__ == "__main__":
    unittest.main()
