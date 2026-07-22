"""Unit tests for the walk-forward, PIT-correct dimension-aware composite signal."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SN = ROOT / "Structured Narrative"
sys.path.insert(0, str(SN))

from composite_signal import (  # noqa: E402
    build_composite_signal,
    expanding_signal_weight,
    expanding_standardize,
    latest_composite_weights,
)

PERIOD_COL = "period"  # a non-fiscal period column -> plain string sort


def _periods(n: int) -> list[str]:
    return [f"P{i:02d}" for i in range(n)]


def _panel(periods: list[str], tickers: list[str], values: dict[str, dict[str, float]], dimension: str) -> pd.DataFrame:
    """values[period][ticker] -> signal value. One row per (ticker, period)."""
    rows = []
    for p in periods:
        for t in tickers:
            rows.append({"ticker": t, PERIOD_COL: p, "dimension": dimension, "sig": values[p][t]})
    return pd.DataFrame(rows)


def _rank_matched_signal_and_label(periods: list[str], tickers: list[str], flip_after: int) -> pd.DataFrame:
    """4-ticker panel where 'sig' perfectly rank-agrees with 'label' for the
    first `flip_after` periods (RankIC = +1) and perfectly rank-reverses for
    every period after that (RankIC = -1)."""
    label_rank = {t: float(i + 1) for i, t in enumerate(tickers)}
    reversed_rank = {t: float(len(tickers) - i) for i, t in enumerate(tickers)}
    rows = []
    for pi, p in enumerate(periods):
        sig_rank = label_rank if pi < flip_after else reversed_rank
        for t in tickers:
            rows.append(
                {
                    "ticker": t,
                    PERIOD_COL: p,
                    "dimension": "demand",
                    "sig": sig_rank[t],
                    "label": label_rank[t],
                }
            )
    return pd.DataFrame(rows)


class ExpandingStandardizeTests(unittest.TestCase):
    def test_warmup_periods_are_nan(self):
        periods = _periods(8)
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        values = {p: {t: float(i) + pi * 10 for i, t in enumerate(tickers)} for pi, p in enumerate(periods)}
        df = _panel(periods, tickers, values, "demand")
        out = expanding_standardize(df, "sig", period_col=PERIOD_COL, min_periods=4)
        warmup_periods = set(periods[:4])
        warmup_mask = df[PERIOD_COL].isin(warmup_periods)
        self.assertTrue(out[warmup_mask].isna().all())
        self.assertTrue(out[~warmup_mask].notna().all())

    def test_no_leakage_future_periods_do_not_affect_past(self):
        periods = _periods(8)
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        values = {p: {t: float(i) + pi * 10 for i, t in enumerate(tickers)} for pi, p in enumerate(periods)}
        full_df = _panel(periods, tickers, values, "demand")
        full_out = expanding_standardize(full_df, "sig", period_col=PERIOD_COL, min_periods=4)

        # Perturb the raw values of the two most recent periods (P06, P07) --
        # this must not change anything computed for earlier periods.
        perturbed_values = {p: dict(v) for p, v in values.items()}
        for t in tickers:
            perturbed_values["P06"][t] += 1000.0
            perturbed_values["P07"][t] -= 5000.0
        perturbed_df = _panel(periods, tickers, perturbed_values, "demand")
        perturbed_out = expanding_standardize(perturbed_df, "sig", period_col=PERIOD_COL, min_periods=4)

        early_mask = full_df[PERIOD_COL].isin(["P04", "P05"])
        pd.testing.assert_series_equal(
            full_out[early_mask].reset_index(drop=True),
            perturbed_out[early_mask].reset_index(drop=True),
        )

    def test_dimension_sparsity_leaves_other_dimensions_untouched(self):
        periods = _periods(6)
        tickers = ["AAA", "BBB"]
        demand_values = {p: {t: float(i) + pi for i, t in enumerate(tickers)} for pi, p in enumerate(periods)}
        demand_df = _panel(periods, tickers, demand_values, "demand")
        narrative_df = _panel(periods, tickers, demand_values, "management_confidence")
        narrative_df["sig"] = np.nan  # a signal that never applies to this dimension
        df = pd.concat([demand_df, narrative_df], ignore_index=True)
        out = expanding_standardize(df, "sig", period_col=PERIOD_COL, min_periods=4)
        self.assertTrue(out[df["dimension"] == "management_confidence"].isna().all())


class ExpandingSignalWeightTests(unittest.TestCase):
    def test_early_weight_is_positive_when_history_is_all_positive(self):
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        periods = _periods(12)
        df = _rank_matched_signal_and_label(periods, tickers, flip_after=4)
        w = expanding_signal_weight(df, "sig", "label", period_col=PERIOD_COL, min_periods=4)
        first_eligible = df[PERIOD_COL] == "P04"
        self.assertTrue((w[first_eligible] == 1.0).all())

    def test_weight_flips_negative_once_enough_contrary_history_accumulates(self):
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        periods = _periods(12)
        # 4 positive periods (P00-P03), then 8 negative periods (P04-P11).
        df = _rank_matched_signal_and_label(periods, tickers, flip_after=4)
        w = expanding_signal_weight(df, "sig", "label", period_col=PERIOD_COL, min_periods=4)
        last_period = df[PERIOD_COL] == "P11"
        # prior = 4 periods @ +1.0, 7 periods @ -1.0 -> mean = (4 - 7) / 11
        expected = (4 - 7) / 11
        self.assertTrue(np.allclose(w[last_period].values, expected))

    def test_no_leakage_future_periods_do_not_affect_past_weight(self):
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        periods = _periods(10)
        full_df = _rank_matched_signal_and_label(periods, tickers, flip_after=4)
        full_w = expanding_signal_weight(full_df, "sig", "label", period_col=PERIOD_COL, min_periods=4)

        truncated_periods = periods[:6]
        truncated_df = full_df[full_df[PERIOD_COL].isin(truncated_periods)].reset_index(drop=True)
        truncated_w = expanding_signal_weight(truncated_df, "sig", "label", period_col=PERIOD_COL, min_periods=4)

        for p in ["P04", "P05"]:
            full_vals = full_w[full_df[PERIOD_COL] == p].reset_index(drop=True)
            trunc_vals = truncated_w[truncated_df[PERIOD_COL] == p].reset_index(drop=True)
            pd.testing.assert_series_equal(full_vals, trunc_vals)


class BuildCompositeSignalTests(unittest.TestCase):
    def test_warmup_periods_are_nan(self):
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        periods = _periods(10)
        df = _rank_matched_signal_and_label(periods, tickers, flip_after=10)
        df = df.rename(columns={"sig": "llm_level"})
        composite = build_composite_signal(
            df, "label", period_col=PERIOD_COL, input_signals=["llm_level"], min_periods=4,
        )
        warmup_mask = df[PERIOD_COL].isin(periods[:4])
        self.assertTrue(composite[warmup_mask].isna().all())

    def test_degenerates_to_single_signal_when_only_one_input_has_history(self):
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        periods = _periods(10)
        # sig always rank-agrees with label -> weight is always positive (+1.0),
        # so the composite should reduce exactly to the standardized signal.
        df = _rank_matched_signal_and_label(periods, tickers, flip_after=10)
        df = df.rename(columns={"sig": "llm_level"})
        composite = build_composite_signal(
            df, "label", period_col=PERIOD_COL, input_signals=["llm_level"], min_periods=4,
        )
        standalone = expanding_standardize(df, "llm_level", period_col=PERIOD_COL, min_periods=4)
        eligible = standalone.notna()
        pd.testing.assert_series_equal(
            composite[eligible].reset_index(drop=True),
            standalone[eligible].reset_index(drop=True),
        )

    def test_renormalizes_across_multiple_contributing_signals(self):
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        periods = _periods(10)
        base = _rank_matched_signal_and_label(periods, tickers, flip_after=10)
        df = base.rename(columns={"sig": "llm_level"}).copy()
        # A second input signal, deliberately on a very different raw scale,
        # that also always rank-agrees with the label.
        df["change_magnitude"] = df["llm_level"] * 100.0 + 5.0

        composite = build_composite_signal(
            df,
            "label",
            period_col=PERIOD_COL,
            input_signals=["llm_level", "change_magnitude"],
            min_periods=4,
        )
        z_llm = expanding_standardize(df, "llm_level", period_col=PERIOD_COL, min_periods=4)
        z_chg = expanding_standardize(df, "change_magnitude", period_col=PERIOD_COL, min_periods=4)
        w_llm = expanding_signal_weight(df, "llm_level", "label", period_col=PERIOD_COL, min_periods=4)
        w_chg = expanding_signal_weight(df, "change_magnitude", "label", period_col=PERIOD_COL, min_periods=4)
        expected = (w_llm * z_llm + w_chg * z_chg) / (w_llm.abs() + w_chg.abs())

        eligible = expected.notna()
        self.assertTrue(eligible.any())
        pd.testing.assert_series_equal(
            composite[eligible].reset_index(drop=True),
            expected[eligible].reset_index(drop=True),
        )

    def test_sparse_dimension_uses_only_its_available_signal(self):
        # >= 3 tickers per period so expanding_signal_weight's per-period
        # Spearman IC is actually computable (it needs n >= 3).
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        periods = _periods(8)
        demand = _rank_matched_signal_and_label(periods, tickers, flip_after=8)
        demand = demand.rename(columns={"sig": "llm_level"})
        demand["dimension"] = "demand"
        demand["agrees_with_quant"] = demand["llm_level"]  # a second signal, only present here

        narrative = demand.copy()
        narrative["dimension"] = "management_confidence"
        narrative["agrees_with_quant"] = np.nan  # this signal never applies to narrative-only dims

        df = pd.concat([demand, narrative], ignore_index=True)
        composite = build_composite_signal(
            df,
            "label",
            period_col=PERIOD_COL,
            input_signals=["llm_level", "agrees_with_quant"],
            min_periods=4,
        )
        narrative_mask = df["dimension"] == "management_confidence"
        z_llm_narrative = expanding_standardize(
            df[narrative_mask], "llm_level", period_col=PERIOD_COL, min_periods=4,
        )
        eligible = z_llm_narrative.notna()
        self.assertTrue(eligible.any())
        pd.testing.assert_series_equal(
            composite[narrative_mask][eligible].reset_index(drop=True),
            z_llm_narrative[eligible].reset_index(drop=True),
        )


class LatestCompositeWeightsTests(unittest.TestCase):
    def test_reports_final_period_weight_per_dimension_and_signal(self):
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        periods = _periods(12)
        df = _rank_matched_signal_and_label(periods, tickers, flip_after=4)
        df = df.rename(columns={"sig": "llm_level"})
        weights = latest_composite_weights(
            df, "label", period_col=PERIOD_COL, input_signals=["llm_level"], min_periods=4,
        )
        self.assertIn("demand", weights)
        self.assertIn("llm_level", weights["demand"])
        self.assertAlmostEqual(weights["demand"]["llm_level"], (4 - 7) / 11, places=4)

    def test_omits_dimensions_without_enough_history(self):
        tickers = ["AAA", "BBB", "CCC", "DDD"]
        periods = _periods(3)  # fewer periods than min_periods
        df = _rank_matched_signal_and_label(periods, tickers, flip_after=3)
        df = df.rename(columns={"sig": "llm_level"})
        weights = latest_composite_weights(
            df, "label", period_col=PERIOD_COL, input_signals=["llm_level"], min_periods=4,
        )
        self.assertEqual(weights, {})


if __name__ == "__main__":
    unittest.main()
