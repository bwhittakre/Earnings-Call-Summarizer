"""Smoke tests for consolidated feature panel HTML report."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

from panel_html import EvidenceLookups, build_consolidated_html, summarize_ticker_quarter  # noqa: E402


def _sample_panel(ticker: str, fp: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "ticker": ticker,
                "fiscal_period": fp,
                "dimension": "demand",
                "llm_level": 1.5,
                "change_magnitude": 0.2,
                "surprise_magnitude": 0.8,
                "quant_z": -0.4,
                "narrative_quant_gap": 1.2,
                "abs_narrative_quant_gap": 1.2,
                "is_divergence": True,
                "any_quant_divergence": True,
                "has_delta": True,
                "has_level": True,
                "has_surprise": True,
                "agrees_with_quant": False,
                "signal_stack": "bullish_level|surprise_bullish|quant_diverges",
                "level_rationale": "Strong demand cited.",
                "delta_rationale": "Improved sequentially.",
                "surprise_rationale": "Beat expectations.",
            },
            {
                "ticker": ticker,
                "fiscal_period": fp,
                "dimension": "margins",
                "llm_level": 0.5,
                "change_magnitude": 0.0,
                "surprise_magnitude": 0.1,
                "quant_z": 0.1,
                "narrative_quant_gap": 0.0,
                "abs_narrative_quant_gap": 0.0,
                "is_divergence": False,
                "any_quant_divergence": False,
                "has_delta": True,
                "has_level": True,
                "has_surprise": True,
                "agrees_with_quant": True,
                "signal_stack": "neutral_level|surprise_inline",
                "level_rationale": "Stable margins.",
                "delta_rationale": "Flat quarter.",
                "surprise_rationale": "In line.",
            },
        ]
    )


class ConsolidatedPanelReportTests(unittest.TestCase):
    def test_summarize_ticker_quarter(self):
        stats = summarize_ticker_quarter(_sample_panel("TST", "FY2025-Q1"))
        self.assertEqual(stats["divergence_count"], 1)
        self.assertIsNotNone(stats["level_avg"])

    def test_build_consolidated_html_markers(self):
        stacked = pd.concat(
            [_sample_panel("AAA", "FY2025-Q1"), _sample_panel("BBB", "FY2025-Q1")],
            ignore_index=True,
        )
        empty = EvidenceLookups(level={}, delta={}, surprise={})
        html = build_consolidated_html(
            stacked,
            {"AAA": empty, "BBB": empty},
            tickers=["AAA", "BBB"],
            fiscal_periods=["FY2025-Q1"],
            default_quarter="FY2025-Q1",
            sector_label="test_sector",
            generated_at="2026-01-01T00:00:00Z",
        )
        self.assertIn('data-ticker="AAA"', html)
        self.assertIn('data-ticker="BBB"', html)
        self.assertIn('class="detail-row"', html)
        self.assertIn('data-mode="compare"', html)
        self.assertIn('data-mode="browse"', html)
        self.assertIn("Compare by quarter", html)
        self.assertIn("Browse by company", html)
        self.assertIn('class="toggle"', html)

    def test_build_script_runs_if_panels_exist(self):
        script = SN / "build_consolidated_panel_report.py"
        msft_panel = SN / "output" / "MSFT" / "csv" / "feature_panel.csv"
        if not msft_panel.exists():
            self.skipTest("MSFT feature panel not present")
        import subprocess

        result = subprocess.run(
            [sys.executable, str(script), "--tickers", "MSFT"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        out = SN / "output" / "cross_company" / "reports" / "consolidated_feature_panel.html"
        self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
