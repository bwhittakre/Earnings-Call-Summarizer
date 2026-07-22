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
    PRIMARY_HYPOTHESES,
    _spearman_ic,
    agreement_effect_stats,
    apply_dev_holdout_split,
    benjamini_hochberg,
    bootstrap_rank_ic_mean,
    cluster_bootstrap_mean_diff,
    cross_section_counts,
    evaluate_signals,
    is_primary_hypothesis,
    leaderboard_rows,
    leave_one_ticker_out,
    primary_hypothesis_rows,
    summarize_ics,
    walk_forward_period_ics,
)
from rank_ic_html import (  # noqa: E402
    build_rank_ic_report_html,
    company_period_signal_rows,
)
from composite_signal import build_composite_signal  # noqa: E402


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


def _composite_ready_frame() -> pd.DataFrame:
    """3 periods x 4 tickers x 1 dimension, with 'sig' always rank-matching
    the label -- enough history for build_composite_signal (min_periods=1)
    to produce a defined composite_score from period 2 onward."""
    tickers = {"AAA": 1.0, "BBB": 2.0, "CCC": 3.0, "DDD": 4.0}
    periods = ["FY2025-Q1", "FY2025-Q2", "FY2025-Q3"]
    rows = []
    for p in periods:
        for t, lbl in tickers.items():
            rows.append(
                {
                    "ticker": t,
                    "fiscal_period": p,
                    "dimension": "demand",
                    "sig": lbl,
                    "alpha_spec_0_90": lbl,
                }
            )
    return pd.DataFrame(rows)


class CompositeSignalIntegrationTests(unittest.TestCase):
    """composite_score is just another signal column once built -- these
    confirm it flows through the existing generic leaderboard/HTML plumbing
    (the --composite smoke test) and that its presence never perturbs any
    other signal's own walk-forward result (the --no-composite regression
    guard, at the unit level -- main() itself reads from disk so isn't
    exercised directly here)."""

    def test_composite_score_flows_through_leaderboard_and_html(self):
        df = _composite_ready_frame()
        df["composite_score"] = build_composite_signal(
            df, "alpha_spec_0_90", period_col="fiscal_period", input_signals=["sig"], min_periods=1,
        )
        self.assertTrue(df["composite_score"].notna().any())

        summary, _ = evaluate_signals(df, ["sig", "composite_score"], "alpha_spec_0_90")
        self.assertIn("composite_score", summary)

        blocks = {"asof": {"0_56": summary}}
        rows = leaderboard_rows(blocks)
        self.assertTrue(any(r["signal"] == "composite_score" for r in rows))

        report = {
            "generated_at": "2026-01-01T00:00:00+00:00",
            "tickers": ["AAA", "BBB", "CCC", "DDD"],
            "horizons": ["0_56"],
            "horizon_windows": {"0_56": "T+7 to T+63 (combined)"},
            "primary_label_key": "asof",
            "primary_horizon": "0_56",
            "leaderboard": rows,
            "jackknife": [],
            "agreement_effect": [],
            "by_label": blocks,
        }
        html = build_rank_ic_report_html(report, period_ics=[], company_period=[])
        self.assertIn("composite_score", html)

    def test_composite_score_column_does_not_change_other_signal_results(self):
        without = _composite_ready_frame()
        with_composite = without.copy()
        with_composite["composite_score"] = build_composite_signal(
            with_composite,
            "alpha_spec_0_90",
            period_col="fiscal_period",
            input_signals=["sig"],
            min_periods=1,
        )

        summary_without, period_without = evaluate_signals(without, ["sig"], "alpha_spec_0_90")
        summary_with, period_with = evaluate_signals(with_composite, ["sig"], "alpha_spec_0_90")

        self.assertEqual(summary_without, summary_with)
        pd.testing.assert_frame_equal(period_without, period_with)


class ClusterBootstrapTests(unittest.TestCase):
    def _company_period_frame(self) -> pd.DataFrame:
        # 4 tickers x 2 periods; True group always higher than False group,
        # but by a DIFFERENT amount per period, so calendar_period clustering
        # produces a different (wider) CI than ticker clustering on this fixture.
        rows = []
        for t in ["AAA", "BBB", "CCC", "DDD"]:
            for p, gap in [("2024-Q1", 0.05), ("2024-Q2", 0.09)]:
                rows.append(
                    {
                        "ticker": t,
                        "period_end_calendar_quarter": p,
                        "flag": True,
                        "ret": 0.02 + gap,
                    }
                )
                rows.append(
                    {
                        "ticker": t,
                        "period_end_calendar_quarter": p,
                        "flag": False,
                        "ret": 0.02,
                    }
                )
        return pd.DataFrame(rows)

    def test_ticker_cluster_matches_point_estimate(self):
        df = self._company_period_frame()
        out = cluster_bootstrap_mean_diff(df, "flag", "ret", cluster_col="ticker", n_boot=300, seed=1)
        self.assertEqual(out["n_clusters"], 4)
        self.assertAlmostEqual(out["mean_diff"], 0.07, places=6)
        self.assertIsNotNone(out["ci_low"])
        self.assertIsNotNone(out["p_value"])

    def test_calendar_period_cluster_uses_period_as_unit(self):
        df = self._company_period_frame()
        out = cluster_bootstrap_mean_diff(
            df, "flag", "ret", cluster_col="calendar_period", n_boot=300, seed=1
        )
        self.assertEqual(out["n_clusters"], 2)
        self.assertAlmostEqual(out["mean_diff"], 0.07, places=6)

    def test_company_period_cluster_finest_unit(self):
        df = self._company_period_frame()
        out = cluster_bootstrap_mean_diff(
            df, "flag", "ret", cluster_col="company_period", n_boot=300, seed=1
        )
        self.assertEqual(out["n_clusters"], 8)

    def test_unknown_cluster_col_raises(self):
        df = self._company_period_frame()
        with self.assertRaises(ValueError):
            cluster_bootstrap_mean_diff(df, "flag", "ret", cluster_col="nonsense")

    def test_single_cluster_returns_none_ci(self):
        df = self._company_period_frame()
        df = df[df["ticker"] == "AAA"]
        out = cluster_bootstrap_mean_diff(df, "flag", "ret", cluster_col="ticker", n_boot=100)
        self.assertEqual(out["n_clusters"], 1)
        self.assertIsNone(out["ci_low"])

    def test_agreement_effect_stats_accepts_cluster_col(self):
        df = pd.DataFrame(
            {
                "ticker": ["AAA", "AAA", "BBB", "BBB"],
                "dimension": ["demand"] * 4,
                "period_end_calendar_quarter": ["2024-Q1", "2024-Q2", "2024-Q1", "2024-Q2"],
                "agrees_with_quant": [True, False, True, False],
                "alpha_spec_0_90": [0.05, -0.02, 0.06, -0.01],
            }
        )
        stats = agreement_effect_stats(
            df, "alpha_spec_0_90", dimension="demand", cluster_col="calendar_period", n_boot=100, seed=1
        )
        self.assertEqual(stats["cluster_col"], "calendar_period")
        self.assertIn("p_value", stats)


class RankIcBootstrapTests(unittest.TestCase):
    def test_too_few_periods_returns_none(self):
        out = bootstrap_rank_ic_mean(pd.DataFrame({"rank_ic": [0.1, 0.2]}))
        self.assertIsNone(out["mean"])

    def test_consistent_positive_ic_yields_positive_mean_and_small_pvalue(self):
        period_ics = pd.DataFrame({"rank_ic": [0.3, 0.35, 0.28, 0.31, 0.33, 0.29]})
        out = bootstrap_rank_ic_mean(period_ics, n_boot=500, seed=1)
        self.assertEqual(out["n_periods"], 6)
        self.assertGreater(out["mean"], 0)
        self.assertLess(out["ci_low"], out["mean"])
        self.assertLess(out["mean"], out["ci_high"])
        self.assertLess(out["p_value"], 0.2)

    def test_zero_centered_ic_yields_wide_ci_spanning_zero(self):
        period_ics = pd.DataFrame({"rank_ic": [0.3, -0.3, 0.2, -0.2, 0.1, -0.1]})
        out = bootstrap_rank_ic_mean(period_ics, n_boot=500, seed=1)
        self.assertLessEqual(out["ci_low"], 0.0)
        self.assertGreaterEqual(out["ci_high"], 0.0)


class BenjaminiHochbergTests(unittest.TestCase):
    def test_preserves_input_order(self):
        pvals = [0.2, 0.001, None, 0.04]
        out = benjamini_hochberg(pvals)
        self.assertEqual(len(out), 4)
        self.assertIsNone(out[2]["q_value"])
        self.assertFalse(out[2]["reject"])

    def test_small_pvalues_rejected_large_not(self):
        # BH step-up: only the smallest p-value clears i/m*alpha here (0.001 <=
        # 1/15*0.05); every later rank's p exceeds its own threshold, so nothing
        # else survives -- this is the expected, harsher-than-uncorrected result.
        pvals = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 0.216, 0.222, 0.251, 0.269, 0.275, 0.34]
        out = benjamini_hochberg(pvals, alpha=0.05)
        self.assertTrue(out[0]["reject"])
        self.assertFalse(out[1]["reject"])
        self.assertFalse(out[-1]["reject"])
        self.assertLess(out[0]["q_value"], out[1]["q_value"])

    def test_all_none_returns_no_rejections(self):
        out = benjamini_hochberg([None, None])
        self.assertTrue(all(o["q_value"] is None and not o["reject"] for o in out))

    def test_empty_list(self):
        self.assertEqual(benjamini_hochberg([]), [])


class PrimaryHypothesisTests(unittest.TestCase):
    def test_is_primary_hypothesis_matches_known_pairs(self):
        self.assertTrue(is_primary_hypothesis("quant_z_pit", "demand"))
        self.assertTrue(is_primary_hypothesis("agrees_with_quant", "margins"))
        self.assertFalse(is_primary_hypothesis("quant_z_pit", "margins"))
        self.assertFalse(is_primary_hypothesis("llm_level", "demand"))

    def test_primary_hypothesis_rows_covers_every_declared_hypothesis(self):
        period_df = pd.DataFrame(
            {
                "signal": ["quant_z_pit"] * 6,
                "dimension": ["demand"] * 6,
                "rank_ic": [0.2, 0.25, 0.18, 0.22, 0.19, 0.24],
            }
        )
        agreement_rows = [
            {"dimension": "demand", "spread": 0.05, "ci_low": 0.01, "ci_high": 0.09, "n_agree": 4, "n_disagree": 4, "n_tickers": 4, "p_value": 0.03},
            {"dimension": "margins", "spread": 0.02, "ci_low": -0.01, "ci_high": 0.05, "n_agree": 4, "n_disagree": 4, "n_tickers": 4, "p_value": 0.4},
            {"dimension": "guidance", "spread": None, "ci_low": None, "ci_high": None, "n_agree": 0, "n_disagree": 0, "n_tickers": 0, "p_value": None},
        ]
        rows = primary_hypothesis_rows(period_df, agreement_rows, fam="asof", horizon="0_56", n_boot=200)
        self.assertEqual(len(rows), len(PRIMARY_HYPOTHESES))
        by_signal_dim = {(r["signal"], r["dimension"]): r for r in rows}
        quant_row = by_signal_dim[("quant_z_pit", "demand")]
        self.assertIsNotNone(quant_row["stat"])
        self.assertIsNotNone(quant_row["p_value"])
        demand_agree_row = by_signal_dim[("agrees_with_quant", "demand")]
        self.assertAlmostEqual(demand_agree_row["stat"], 0.05)
        guidance_row = by_signal_dim[("agrees_with_quant", "guidance")]
        self.assertIsNone(guidance_row["p_value"])


class CrossSectionCountsTests(unittest.TestCase):
    def test_counts_distinct_tickers_per_period(self):
        df = pd.DataFrame(
            {
                "ticker": ["AAA", "BBB", "AAA", "CCC", "CCC"],
                "period_end_calendar_quarter": ["2024-Q1", "2024-Q1", "2024-Q2", "2024-Q2", "2024-Q2"],
            }
        )
        counts = cross_section_counts(df, "period_end_calendar_quarter")
        self.assertEqual(counts, {"2024-Q1": 2, "2024-Q2": 2})

    def test_missing_columns_returns_empty(self):
        df = pd.DataFrame({"foo": [1, 2]})
        self.assertEqual(cross_section_counts(df, "period_end_calendar_quarter"), {})


class DevHoldoutSplitTests(unittest.TestCase):
    def _quarterly_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "period_end_calendar_quarter": ["2022-Q1", "2022-Q2", "2023-Q1", "2023-Q2", "2024-Q1"],
                "val": [1, 2, 3, 4, 5],
            }
        )

    def test_no_split_args_returns_unchanged(self):
        df = self._quarterly_frame()
        out = apply_dev_holdout_split(df, "period_end_calendar_quarter")
        self.assertEqual(len(out), len(df))

    def test_dev_only_keeps_at_or_before_cutoff(self):
        df = self._quarterly_frame()
        out = apply_dev_holdout_split(
            df, "period_end_calendar_quarter", dev_cutoff="2023-Q1", dev_only=True
        )
        self.assertEqual(sorted(out["period_end_calendar_quarter"]), ["2022-Q1", "2022-Q2", "2023-Q1"])

    def test_holdout_only_keeps_at_or_after_start(self):
        df = self._quarterly_frame()
        out = apply_dev_holdout_split(
            df, "period_end_calendar_quarter", holdout_start="2023-Q2", holdout_only=True
        )
        self.assertEqual(sorted(out["period_end_calendar_quarter"]), ["2023-Q2", "2024-Q1"])

    def test_both_bounds_drop_no_mans_land(self):
        df = self._quarterly_frame()
        out = apply_dev_holdout_split(
            df,
            "period_end_calendar_quarter",
            dev_cutoff="2022-Q2",
            holdout_start="2024-Q1",
        )
        self.assertEqual(sorted(out["period_end_calendar_quarter"]), ["2022-Q1", "2022-Q2", "2024-Q1"])

    def test_holdout_only_with_only_dev_cutoff_uses_implied_complement(self):
        # Regression: passing --dev-cutoff alone with --holdout-only must NOT
        # fall back to "everything" -- holdout is the implied complement
        # (strictly after the cutoff), even though holdout_start was never set.
        df = self._quarterly_frame()
        out = apply_dev_holdout_split(
            df, "period_end_calendar_quarter", dev_cutoff="2023-Q1", holdout_only=True
        )
        self.assertEqual(sorted(out["period_end_calendar_quarter"]), ["2023-Q2", "2024-Q1"])

    def test_dev_only_with_only_holdout_start_uses_implied_complement(self):
        df = self._quarterly_frame()
        out = apply_dev_holdout_split(
            df, "period_end_calendar_quarter", holdout_start="2023-Q2", dev_only=True
        )
        self.assertEqual(sorted(out["period_end_calendar_quarter"]), ["2022-Q1", "2022-Q2", "2023-Q1"])

    def test_dev_cutoff_alone_without_only_flag_returns_full_frame(self):
        # dev U holdout is a full complementary partition when only one bound
        # is given and no *_only flag restricts to one side -- this is the
        # documented "the split flag alone doesn't drop data" default.
        df = self._quarterly_frame()
        out = apply_dev_holdout_split(df, "period_end_calendar_quarter", dev_cutoff="2023-Q1")
        self.assertEqual(len(out), len(df))

    def test_dev_only_and_holdout_only_mutually_exclusive(self):
        df = self._quarterly_frame()
        with self.assertRaises(ValueError):
            apply_dev_holdout_split(
                df,
                "period_end_calendar_quarter",
                dev_cutoff="2023-Q1",
                holdout_start="2023-Q2",
                dev_only=True,
                holdout_only=True,
            )


if __name__ == "__main__":
    unittest.main()
