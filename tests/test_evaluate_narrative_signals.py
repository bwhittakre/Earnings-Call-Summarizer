"""Unit tests for narrative signal IC evaluation helpers."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

from evaluate_narrative_signals import (  # noqa: E402
    _spearman_ic,
    leaderboard_rows,
    leave_one_ticker_out,
    summarize_ics,
    walk_forward_period_ics,
)


class SpearmicIcTests(unittest.TestCase):
    def test_perfect_rank_agreement(self):
        x = pd.Series([1.0, 2.0, 3.0, 4.0])
        y = pd.Series([10.0, 20.0, 30.0, 40.0])
        self.assertAlmostEqual(_spearman_ic(x, y), 1.0)

    def test_perfect_rank_reversal(self):
        x = pd.Series([1.0, 2.0, 3.0, 4.0])
        y = pd.Series([40.0, 30.0, 20.0, 10.0])
        self.assertAlmostEqual(_spearman_ic(x, y), -1.0)

    def test_too_few_points(self):
        self.assertIsNone(_spearman_ic(pd.Series([1.0, 2.0]), pd.Series([3.0, 4.0])))


class WalkForwardTests(unittest.TestCase):
    def test_period_ics_and_hit_rate(self):
        df = pd.DataFrame(
            {
                "fiscal_period": ["FY2025-Q1"] * 4 + ["FY2025-Q2"] * 4,
                "signal": [1, 2, 3, 4, 4, 3, 2, 1],
                "label": [1, 2, 3, 4, 1, 2, 3, 4],
            }
        )
        period = walk_forward_period_ics(df, "signal", "label")
        self.assertEqual(len(period), 2)
        self.assertAlmostEqual(period.loc[period.fiscal_period == "FY2025-Q1", "rank_ic"].iloc[0], 1.0)
        self.assertAlmostEqual(period.loc[period.fiscal_period == "FY2025-Q2", "rank_ic"].iloc[0], -1.0)
        summary = summarize_ics(period)
        self.assertEqual(summary["n_periods"], 2)
        self.assertEqual(summary["positive_rank_ic_periods"], 1)
        self.assertAlmostEqual(summary["positive_rank_ic_hit_rate"], 0.5)
        self.assertAlmostEqual(summary["rank_ic_mean"], 0.0)


class LeaderboardAndJackknifeTests(unittest.TestCase):
    def test_leaderboard_sorts_by_rank_ic_mean(self):
        blocks = {
            "event": {
                "a": {
                    "walk_forward": {"rank_ic_mean": -0.1, "rank_ic_ir": -0.5, "n_periods": 3, "positive_rank_ic_hit_rate": 0.3},
                    "pooled_rank_ic": -0.05,
                    "n_rows": 10,
                    "universe": "all",
                },
                "b": {
                    "walk_forward": {"rank_ic_mean": 0.2, "rank_ic_ir": 0.8, "n_periods": 3, "positive_rank_ic_hit_rate": 0.7},
                    "pooled_rank_ic": 0.1,
                    "n_rows": 10,
                    "universe": "all",
                },
            }
        }
        rows = leaderboard_rows(blocks)
        self.assertEqual(rows[0]["signal"], "b")
        self.assertEqual(rows[1]["signal"], "a")

    def test_leave_one_ticker_out_emits_held_out_rows(self):
        rows = []
        for t, offset in [("AAA", 0), ("BBB", 1), ("CCC", 2)]:
            for i in range(4):
                rows.append(
                    {
                        "ticker": t,
                        "fiscal_period": "FY2025-Q1",
                        "dimension": f"d{i}",
                        "sig": float(i + offset),
                        "alpha_spec_0_90": float(i),
                    }
                )
        df = pd.DataFrame(rows)
        out = leave_one_ticker_out(df, ["sig"], "alpha_spec_0_90")
        held = {r["held_out_ticker"] for r in out}
        self.assertEqual(held, {"AAA", "BBB", "CCC"})
        self.assertTrue(all(r["signal"] == "sig" for r in out))


if __name__ == "__main__":
    unittest.main()
