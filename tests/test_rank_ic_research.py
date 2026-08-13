"""Tests for native Rank IC Research Explore/Explain helpers."""
from __future__ import annotations

import pytest

from services.earnings_monitor.dashboard.rank_ic_research import (
    ALL_MEAN,
    EXPLORE_ORDER,
    EXPLAIN_ORDER,
    HORIZON_KEYS,
    RANK_IC_VIEWS,
    all_mean_blocked_message,
    flag_dominant_members,
    horizon_fingerprint,
    join_street_overlay,
    period_leave_one_out,
    subset_leaderboard_rows,
)
from services.earnings_monitor.dashboard.views import RANK_IC_VIEWS as VIEWS_EXPORT
from services.earnings_monitor.dashboard.views import VIEWS


def _cell(
    ticker: str,
    period: str,
    sig: float,
    ret: float,
    *,
    signal: str = "llm_level",
    dimension: str = "demand",
    horizon: str = "0_56",
) -> dict:
    return {
        "label_key": "asof",
        "horizon": horizon,
        "ticker": ticker,
        "period": period,
        "signal": signal,
        "dimension": dimension,
        "signal_mean": sig,
        "label_mean": ret,
        "n": 1,
    }


def _four_name_period(*, flip_last: bool = False) -> list[dict]:
    names = [
        ("AAA", 1.0, 0.01),
        ("BBB", 2.0, 0.02),
        ("CCC", 3.0, 0.03),
        ("DDD", 4.0, -0.04 if flip_last else 0.04),
    ]
    return [_cell(t, "2025-Q1", s, r) for t, s, r in names]


def test_rank_ic_views_explore_and_explain_no_signal_research() -> None:
    assert "Signal research" not in RANK_IC_VIEWS
    assert "Signal research" not in VIEWS
    assert list(EXPLORE_ORDER) + list(EXPLAIN_ORDER) == list(RANK_IC_VIEWS)
    assert RANK_IC_VIEWS is VIEWS_EXPORT


def test_subset_rank_ic_parity_with_html_helpers() -> None:
    company_period = []
    for period, base in (("2025-Q1", 0.0), ("2025-Q2", 1.0)):
        for ticker, sig, lab in (
            ("AAPL", 1.0 + base, 0.01 + base * 0.01),
            ("MSFT", 2.0 + base, 0.02 + base * 0.01),
            ("NVDA", 3.0 + base, 0.03 + base * 0.01),
            ("META", 4.0 + base, -0.04 - base * 0.01),
        ):
            company_period.append(_cell(ticker, period, sig, lab))
    rows = subset_leaderboard_rows(
        company_period,
        ["AAPL", "MSFT", "NVDA"],
        label="asof",
        horizon="0_56",
        dimension="demand",
        signals=["llm_level"],
    )
    assert len(rows) == 1
    assert rows[0]["n_periods"] == 2
    assert rows[0]["rank_ic_mean"] == pytest.approx(1.0)


def test_quarter_drivers_loo_delta_four_names() -> None:
    aligned = period_leave_one_out(_four_name_period(flip_last=False))
    assert len(aligned) == 4
    assert aligned[0]["baseline_rank_ic"] == pytest.approx(1.0)
    for row in aligned:
        assert row["loo_rank_ic"] == pytest.approx(1.0)
        assert row["loo_delta"] == pytest.approx(0.0)

    flipped = period_leave_one_out(_four_name_period(flip_last=True))
    baseline = flipped[0]["baseline_rank_ic"]
    assert baseline is not None
    assert baseline < 1.0
    ddd = next(r for r in flipped if r["ticker"] == "DDD")
    assert ddd["loo_rank_ic"] == pytest.approx(1.0)
    assert ddd["loo_delta"] == pytest.approx(1.0 - float(baseline))


def test_measure_dominant_member_flag() -> None:
    members = [
        {"measure_name": "Free Cash Flow", "z_pit": 11.8},
        {"measure_name": "Capex", "z_pit": -0.25},
        {"measure_name": "SBC", "z_pit": 0.10},
    ]
    flagged = flag_dominant_members(members)
    by_name = {r["measure_name"]: r["dominant"] for r in flagged}
    assert by_name["Free Cash Flow"] is True
    assert by_name["Capex"] is False
    assert by_name["SBC"] is False


def test_horizon_fingerprint_five_keys_no_all_mean() -> None:
    company_period = []
    for horizon in HORIZON_KEYS:
        sign = -1.0 if horizon == "0_14" else 1.0
        for ticker, sig in (("AAPL", 1.0), ("MSFT", 2.0), ("NVDA", 3.0), ("META", 4.0)):
            company_period.append(
                _cell(
                    ticker,
                    "2025-Q1",
                    sig,
                    sign * sig * 0.01,
                    horizon=horizon,
                )
            )
    rows = horizon_fingerprint(
        company_period,
        ["AAPL", "MSFT", "NVDA", "META"],
        label="asof",
        dimension="demand",
        signal="llm_level",
    )
    assert [r["horizon"] for r in rows] == list(HORIZON_KEYS)
    by_h = {r["horizon"]: r for r in rows}
    assert by_h["0_14"]["rank_ic_mean"] == pytest.approx(-1.0)
    assert by_h["0_56"]["rank_ic_mean"] == pytest.approx(1.0)
    assert (
        horizon_fingerprint(
            company_period,
            ["AAPL"],
            label="asof",
            dimension=ALL_MEAN,
            signal="llm_level",
        )
        == []
    )
    assert "ALL_MEAN" in all_mean_blocked_message()


def test_street_overlay_joins_revision_and_empty_when_missing() -> None:
    company_period = _four_name_period(flip_last=False)
    panel = [
        {
            "ticker": "AAA",
            "fiscal_period": "2025-Q1",
            "period_end_calendar_quarter": "2025-Q1",
            "quant_guidance_revision_z_pit": 0.5,
        },
        {
            "ticker": "BBB",
            "fiscal_period": "2025-Q1",
            "period_end_calendar_quarter": "2025-Q1",
            "quant_guidance_revision_z_pit": 1.0,
        },
        {
            "ticker": "CCC",
            "fiscal_period": "2025-Q1",
            "period_end_calendar_quarter": "2025-Q1",
            "quant_guidance_revision_z_pit": 1.5,
        },
        {
            "ticker": "DDD",
            "fiscal_period": "2025-Q1",
            "period_end_calendar_quarter": "2025-Q1",
            "quant_guidance_revision_z_pit": 2.0,
        },
    ]
    overlay = join_street_overlay(
        company_period,
        panel,
        label="asof",
        horizon="0_56",
        dimension="demand",
        signal="llm_level",
        tickers=["AAA", "BBB", "CCC", "DDD"],
        period="2025-Q1",
    )
    assert overlay["missing_revision"] is False
    assert overlay["n"] == 4
    assert overlay["n_revision"] == 4
    assert overlay["signal_rank_ic"] == pytest.approx(1.0)
    assert overlay["revision_rank_ic"] == pytest.approx(1.0)
    by_t = {r["ticker"]: r for r in overlay["rows"]}
    assert by_t["DDD"]["revision_z"] == 2.0

    empty = join_street_overlay(
        company_period,
        [],
        label="asof",
        horizon="0_56",
        dimension="demand",
        signal="llm_level",
        tickers=["AAA", "BBB", "CCC", "DDD"],
        period="2025-Q1",
    )
    assert empty["missing_revision"] is True
    assert empty["revision_rank_ic"] is None
    assert all(r["revision_z"] is None for r in empty["rows"])
