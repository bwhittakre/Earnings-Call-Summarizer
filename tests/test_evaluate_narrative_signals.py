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
    agreement_effect_stats,
    evaluate_signals,
    leaderboard_rows,
    leave_one_ticker_out,
    summarize_ics,
    walk_forward_period_ics,
)
from rank_ic_html import (  # noqa: E402
    build_rank_ic_report_html,
    company_period_signal_rows,
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


def _multi_dim_period_frame() -> pd.DataFrame:
    """4 tickers × 2 dimensions × 1 period. Within 'demand' the signal ranks with
    the (shared, per-ticker) label; within 'margins' it's reversed — a single
    pooled cross-section (the old bug) would blend these into a weaker RankIC,
    while the corrected per-dimension test should show +1.0 and -1.0 cleanly."""
    rows = []
    label_by_ticker = {"AAA": 1.0, "BBB": 2.0, "CCC": 3.0, "DDD": 4.0}
    demand_signal = {"AAA": 10.0, "BBB": 20.0, "CCC": 30.0, "DDD": 40.0}
    margins_signal = {"AAA": 40.0, "BBB": 30.0, "CCC": 20.0, "DDD": 10.0}
    for t, lbl in label_by_ticker.items():
        rows.append(
            {
                "ticker": t,
                "fiscal_period": "FY2025-Q1",
                "dimension": "demand",
                "sig": demand_signal[t],
                "alpha_spec_0_90": lbl,
            }
        )
        rows.append(
            {
                "ticker": t,
                "fiscal_period": "FY2025-Q1",
                "dimension": "margins",
                "sig": margins_signal[t],
                "alpha_spec_0_90": lbl,
            }
        )
    return pd.DataFrame(rows)


class WalkForwardTests(unittest.TestCase):
    def test_period_ics_and_hit_rate_single_dimension(self):
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

    def test_period_ics_separate_by_dimension_unit_of_observation(self):
        """The core fix: one period with 2 dimensions x 4 tickers must yield two
        4-point cross-sections (n=4 each), not one pooled 8-point cross-section."""
        df = _multi_dim_period_frame()
        period = walk_forward_period_ics(df, "sig", "alpha_spec_0_90")
        self.assertEqual(len(period), 2)  # one row per dimension, not one pooled row
        self.assertTrue((period["n"] == 4).all())
        demand_row = period[period["dimension"] == "demand"].iloc[0]
        margins_row = period[period["dimension"] == "margins"].iloc[0]
        self.assertAlmostEqual(demand_row["rank_ic"], 1.0)
        self.assertAlmostEqual(margins_row["rank_ic"], -1.0)


class EvaluateSignalsTests(unittest.TestCase):
    def test_by_dimension_and_dimension_mean(self):
        df = _multi_dim_period_frame()
        summary, period_df = evaluate_signals(df, ["sig"], "alpha_spec_0_90")
        self.assertIn("sig", summary)
        by_dim = summary["sig"]["by_dimension"]
        self.assertEqual(set(by_dim.keys()), {"demand", "margins"})
        self.assertAlmostEqual(by_dim["demand"]["walk_forward"]["rank_ic_mean"], 1.0)
        self.assertAlmostEqual(by_dim["margins"]["walk_forward"]["rank_ic_mean"], -1.0)
        self.assertEqual(by_dim["demand"]["n_rows"], 4)
        # dimension_mean averages the two independently-correct per-dimension means.
        self.assertAlmostEqual(summary["sig"]["dimension_mean"]["rank_ic_mean"], 0.0)
        self.assertEqual(summary["sig"]["dimension_mean"]["n_dimensions"], 2)
        self.assertEqual(len(period_df), 2)


class LeaderboardAndJackknifeTests(unittest.TestCase):
    def test_leaderboard_flattens_label_horizon_signal_dimension(self):
        blocks = {
            "asof": {
                "0_56": {
                    "sig": {
                        "by_dimension": {
                            "demand": {
                                "walk_forward": {"rank_ic_mean": 0.2, "rank_ic_ir": 0.8, "n_periods": 3, "positive_rank_ic_hit_rate": 0.7},
                                "pooled_rank_ic": 0.1,
                                "n_rows": 10,
                            },
                            "margins": {
                                "walk_forward": {"rank_ic_mean": -0.1, "rank_ic_ir": -0.5, "n_periods": 3, "positive_rank_ic_hit_rate": 0.3},
                                "pooled_rank_ic": -0.05,
                                "n_rows": 10,
                            },
                        },
                        "dimension_mean": {"rank_ic_mean": 0.05, "n_dimensions": 2},
                        "n_rows": 20,
                        "universe": "investable_ready",
                    }
                }
            }
        }
        rows = leaderboard_rows(blocks)
        # 2 dimension rows + 1 ALL_MEAN row for the single signal.
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["label"] == "asof" and r["horizon"] == "0_56" for r in rows))
        demand_row = next(r for r in rows if r["dimension"] == "demand")
        self.assertAlmostEqual(demand_row["rank_ic_mean"], 0.2)
        all_mean_row = next(r for r in rows if r["dimension"] == "ALL_MEAN")
        self.assertAlmostEqual(all_mean_row["rank_ic_mean"], 0.05)
        # Highest RankIC (demand, 0.2) sorts first.
        self.assertEqual(rows[0]["dimension"], "demand")

    def test_leave_one_ticker_out_emits_dimension_tagged_rows(self):
        rows = []
        for t, offset in [("AAA", 0), ("BBB", 1), ("CCC", 2), ("DDD", 3)]:
            for i, dim in enumerate(["demand", "margins"]):
                rows.append(
                    {
                        "ticker": t,
                        "fiscal_period": "FY2025-Q1",
                        "dimension": dim,
                        "sig": float(i + offset),
                        "alpha_spec_0_90": float(offset),
                    }
                )
        df = pd.DataFrame(rows)
        out = leave_one_ticker_out(df, ["sig"], "alpha_spec_0_90")
        held = {r["held_out_ticker"] for r in out}
        self.assertEqual(held, {"AAA", "BBB", "CCC", "DDD"})
        self.assertTrue(all(r["signal"] == "sig" for r in out))
        self.assertTrue({"demand", "margins"}.issubset({r["dimension"] for r in out}))


class AgreementEffectTests(unittest.TestCase):
    def _agreement_frame(self) -> pd.DataFrame:
        # 4 tickers; agree rows have a clearly higher forward return than disagree rows.
        rows = []
        for t in ["AAA", "BBB", "CCC", "DDD"]:
            rows.append({"ticker": t, "dimension": "demand", "agrees_with_quant": True, "alpha_spec_0_90": 0.05})
            rows.append({"ticker": t, "dimension": "demand", "agrees_with_quant": False, "alpha_spec_0_90": -0.02})
        return pd.DataFrame(rows)

    def test_spread_and_ci_direction(self):
        df = self._agreement_frame()
        stats = agreement_effect_stats(df, "alpha_spec_0_90", dimension="demand", n_boot=200, seed=1)
        self.assertEqual(stats["n_agree"], 4)
        self.assertEqual(stats["n_disagree"], 4)
        self.assertAlmostEqual(stats["mean_return_agree"], 0.05)
        self.assertAlmostEqual(stats["mean_return_disagree"], -0.02)
        self.assertAlmostEqual(stats["spread"], 0.07)
        self.assertIsNotNone(stats["ci_low"])
        self.assertIsNotNone(stats["ci_high"])
        self.assertLessEqual(stats["ci_low"], stats["spread"])
        self.assertGreaterEqual(stats["ci_high"], stats["spread"])
        # Every ticker agrees identically in this fixture, so the bootstrap CI
        # should collapse to (near) the point estimate — no per-ticker variance.
        self.assertAlmostEqual(stats["ci_low"], 0.07, places=6)
        self.assertAlmostEqual(stats["ci_high"], 0.07, places=6)

    def test_empty_selection_returns_zero_counts(self):
        df = self._agreement_frame()
        stats = agreement_effect_stats(df, "alpha_spec_0_90", dimension="guidance", n_boot=50)
        self.assertEqual(stats["n_agree"], 0)
        self.assertEqual(stats["n_disagree"], 0)
        self.assertIsNone(stats["spread"])

    def test_pooled_dimension_none_uses_all_rows(self):
        df = self._agreement_frame()
        stats = agreement_effect_stats(df, "alpha_spec_0_90", dimension=None, n_boot=200, seed=1)
        self.assertEqual(stats["dimension"], "pooled")
        self.assertEqual(stats["n_agree"], 4)


class RankIcHtmlTests(unittest.TestCase):
    def test_company_period_rows_tag_dimension_and_all_mean(self):
        df = pd.DataFrame(
            {
                "ticker": ["AAPL", "AAPL", "MSFT", "MSFT"],
                "fiscal_period": ["FY2025-Q1", "FY2025-Q1", "FY2025-Q1", "FY2025-Q1"],
                "dimension": ["demand", "margins", "demand", "margins"],
                "llm_level": [1.0, 1.5, 0.5, 0.0],
                "alpha_spec_0_90": [0.01, 0.02, -0.01, 0.0],
            }
        )
        rows = company_period_signal_rows(
            df,
            ["llm_level"],
            "alpha_spec_0_90",
            period_col="fiscal_period",
            label_key="asof",
            horizon="0_56",
        )
        dims = {r["dimension"] for r in rows}
        self.assertEqual(dims, {"demand", "margins", "ALL_MEAN"})
        self.assertTrue(all(r["horizon"] == "0_56" for r in rows))
        all_mean_aapl = next(r for r in rows if r["ticker"] == "AAPL" and r["dimension"] == "ALL_MEAN")
        self.assertAlmostEqual(all_mean_aapl["signal_mean"], 1.25)

    def test_build_html_with_multi_horizon_dimension_report(self):
        report = {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "tickers": ["AAPL", "MSFT"],
            "horizons": ["0_56"],
            "horizon_windows": {"0_56": "T+7 to T+63 (combined)"},
            "primary_label_key": "asof",
            "primary_horizon": "0_56",
            "leaderboard": [
                {
                    "signal": "llm_level",
                    "label": "asof",
                    "horizon": "0_56",
                    "horizon_name": "T+7 to T+63 (combined)",
                    "dimension": "demand",
                    "universe": "investable_ready",
                    "rank_ic_mean": 0.2,
                    "rank_ic_ir": 0.5,
                    "pooled_rank_ic": 0.1,
                    "positive_rank_ic_hit_rate": 0.6,
                    "n_periods": 3,
                    "n_rows": 8,
                },
                {
                    "signal": "llm_level",
                    "label": "asof",
                    "horizon": "0_56",
                    "horizon_name": "T+7 to T+63 (combined)",
                    "dimension": "ALL_MEAN",
                    "universe": "investable_ready",
                    "rank_ic_mean": 0.15,
                    "rank_ic_ir": None,
                    "pooled_rank_ic": None,
                    "positive_rank_ic_hit_rate": None,
                    "n_periods": 1,
                    "n_rows": 8,
                },
            ],
            "jackknife": [],
            "agreement_effect": [
                {
                    "dimension": "pooled",
                    "label_key": "asof",
                    "horizon": "0_56",
                    "horizon_name": "T+7 to T+63 (combined)",
                    "n_agree": 4,
                    "n_disagree": 4,
                    "n_tickers": 2,
                    "mean_return_agree": 0.05,
                    "mean_return_disagree": -0.02,
                    "spread": 0.07,
                    "ci_low": 0.02,
                    "ci_high": 0.09,
                    "n_boot": 200,
                }
            ],
            "by_label": {
                "asof": {
                    "0_56": {
                        "llm_level": {
                            "by_dimension": {
                                "demand": {
                                    "walk_forward": {"rank_ic_mean": 0.2},
                                    "pooled_rank_ic": 0.1,
                                    "n_rows": 8,
                                }
                            },
                            "dimension_mean": {"rank_ic_mean": 0.15, "n_dimensions": 1},
                            "universe": "investable_ready",
                        }
                    }
                }
            },
        }
        period_ics = [
            {
                "period": "2025-Q1",
                "period_col": "period_end_calendar_quarter",
                "dimension": "demand",
                "signal": "llm_level",
                "label": "alpha_spec_asof_0_56",
                "label_key": "asof",
                "horizon": "0_56",
                "n": 4,
                "ic": 0.2,
                "rank_ic": 0.2,
                "universe": "investable_ready",
            }
        ]
        company_period = [
            {
                "label_key": "asof",
                "horizon": "0_56",
                "label": "alpha_spec_asof_0_56",
                "period_col": "period_end_calendar_quarter",
                "universe": "investable_ready",
                "ticker": "AAPL",
                "period": "2025-Q1",
                "signal": "llm_level",
                "dimension": "demand",
                "signal_mean": 1.0,
                "label_mean": 0.01,
                "n": 1,
            }
        ]
        out_html = build_rank_ic_report_html(
            report, period_ics=period_ics, company_period=company_period
        )
        self.assertIn("Cross-Company RankIC", out_html)
        self.assertIn("By dimension", out_html)
        self.assertIn("Agreement effect", out_html)
        self.assertIn("data-horizon=\"0_56\"", out_html)
        self.assertIn("data-dimension=", out_html)
        self.assertIn("const DATA =", out_html)
        self.assertIn("llm_level", out_html)


if __name__ == "__main__":
    unittest.main()
