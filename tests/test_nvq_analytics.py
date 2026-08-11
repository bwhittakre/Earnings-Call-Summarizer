"""Unit tests for Narrative vs Quant analytics helpers."""

from __future__ import annotations

from services.earnings_monitor.dashboard.data import DashboardData
from services.earnings_monitor.dashboard.nvq_analytics import (
    calendar_quarter_options,
    compute_agreement_streaks,
    compute_peer_gap_deltas,
    filter_by_calendar_quarters,
)


def _point(
    ticker: str,
    period: str,
    dimension: str,
    *,
    diverge: bool = True,
    gap: float = 1.0,
    calendar_quarter: str | None = None,
) -> dict:
    return {
        "ticker": ticker,
        "fiscal_period": period,
        "calendar_quarter": calendar_quarter or period.replace("FY", ""),
        "dimension": dimension,
        "narrative_level": 1.0,
        "quant_z": 0.0,
        "gap": gap,
        "divergence": diverge,
        "agreement": "Divergence" if diverge else "Aligned",
    }


def test_agreement_streak_grows_on_consecutive_same_agreement():
    points = compute_agreement_streaks(
        [
            _point("AAPL", "FY2024-Q1", "demand", diverge=True, calendar_quarter="2024-Q1"),
            _point("AAPL", "FY2024-Q2", "demand", diverge=True, calendar_quarter="2024-Q2"),
            _point("AAPL", "FY2024-Q3", "demand", diverge=True, calendar_quarter="2024-Q3"),
        ]
    )
    by_period = {row["fiscal_period"]: row for row in points}
    assert by_period["FY2024-Q3"]["diverge_streak"] == 3
    assert by_period["FY2024-Q2"]["agreement_flipped"] is False


def test_agreement_streak_breaks_on_missing_period():
    points = compute_agreement_streaks(
        [
            _point("AAPL", "FY2024-Q1", "demand", diverge=False, calendar_quarter="2024-Q1"),
            _point("AAPL", "FY2024-Q2", "demand", diverge=False, calendar_quarter="2024-Q2"),
            _point("AAPL", "FY2024-Q4", "demand", diverge=True, calendar_quarter="2024-Q4"),
        ]
    )
    by_period = {row["fiscal_period"]: row for row in points}
    assert by_period["FY2024-Q2"]["align_streak"] == 2
    assert by_period["FY2024-Q4"]["diverge_streak"] == 1


def test_agreement_flip_vs_prior_observation():
    points = compute_agreement_streaks(
        [
            _point("MSFT", "FY2025-Q1", "margins", diverge=False, calendar_quarter="2025-Q1"),
            _point("MSFT", "FY2025-Q2", "margins", diverge=True, calendar_quarter="2025-Q2"),
            _point("MSFT", "FY2025-Q3", "margins", diverge=True, calendar_quarter="2025-Q3"),
        ]
    )
    by_period = {row["fiscal_period"]: row for row in points}
    assert by_period["FY2025-Q2"]["agreement_flipped"] is True
    assert by_period["FY2025-Q3"]["diverge_streak"] == 2


def test_peer_gap_delta_uses_median_of_universe():
    focus = [
        _point("AAPL", "FY2025-Q1", "demand", gap=1.0, calendar_quarter="2024-Q4"),
    ]
    peers = [
        _point("AAPL", "FY2025-Q1", "demand", gap=1.0, calendar_quarter="2024-Q4"),
        _point("MSFT", "FY2025-Q1", "demand", gap=0.0, calendar_quarter="2024-Q4"),
        _point("AMZN", "FY2025-Q1", "demand", gap=2.0, calendar_quarter="2024-Q4"),
        _point("MSFT", "FY2025-Q1", "margins", gap=9.0, calendar_quarter="2024-Q4"),
    ]
    enriched = compute_peer_gap_deltas(focus, peers)
    assert len(enriched) == 1
    assert enriched[0]["peer_gap_median"] == 1.0
    assert enriched[0]["peer_n"] == 3
    assert enriched[0]["peer_gap_delta"] == 0.0


def test_narrative_vs_quant_enriches_streak_and_peer_fields():
    data = DashboardData.from_records(
        [
            {
                "ticker": "AAPL",
                "fiscal_period": "FY2025-Q1",
                "period_end_calendar_quarter": "2024-Q4",
                "dimension": "demand",
                "llm_level": 1.0,
                "quant_z_pit": 0.0,
                "narrative_quant_gap": 1.0,
                "any_quant_divergence": True,
            },
            {
                "ticker": "AAPL",
                "fiscal_period": "FY2025-Q2",
                "period_end_calendar_quarter": "2025-Q1",
                "dimension": "demand",
                "llm_level": 1.0,
                "quant_z_pit": 0.0,
                "narrative_quant_gap": 1.0,
                "any_quant_divergence": True,
            },
            {
                "ticker": "MSFT",
                "fiscal_period": "FY2025-Q1",
                "period_end_calendar_quarter": "2024-Q4",
                "dimension": "demand",
                "llm_level": 0.5,
                "quant_z_pit": 0.0,
                "narrative_quant_gap": 0.5,
                "any_quant_divergence": False,
            },
        ]
    )
    points = data.narrative_vs_quant(
        tickers=["AAPL"],
        peer_tickers=["AAPL", "MSFT"],
    )
    assert len(points) == 2
    q1 = next(row for row in points if row["fiscal_period"] == "FY2025-Q1")
    q2 = next(row for row in points if row["fiscal_period"] == "FY2025-Q2")
    assert q1["calendar_quarter"] == "2024-Q4"
    assert q1["agreement"] == "Divergence"
    assert q1["diverge_streak"] == 1
    assert q1["peer_n"] >= 1
    assert q1["peer_gap_median"] is not None
    assert q1["peer_gap_delta"] is not None
    assert q2["diverge_streak"] == 2
    assert q2["agreement_flipped"] is False
    assert q1["align_streak"] == 0
    assert q1["calendar_quarter_fallback"] is False


def test_calendar_quarter_filter_keeps_shared_bucket_despite_fiscal_labels():
    """One calendar quarter must not mix misaligned fiscal FY labels."""
    points = [
        _point("AAPL", "FY2025-Q1", "demand", calendar_quarter="2024-Q4"),
        _point("MSFT", "FY2025-Q1", "demand", calendar_quarter="2025-Q1"),
        _point("AMZN", "FY2024-Q4", "demand", calendar_quarter="2024-Q4"),
    ]
    options = calendar_quarter_options(points)
    assert "2024-Q4" in options
    filtered = filter_by_calendar_quarters(points, ["2024-Q4"])
    tickers = sorted({row["ticker"] for row in filtered})
    assert tickers == ["AAPL", "AMZN"]
    assert all(row["calendar_quarter"] == "2024-Q4" for row in filtered)


def test_calendar_quarter_filter_empty_selection_clears_rows():
    points = [_point("AAPL", "FY2025-Q1", "demand", calendar_quarter="2024-Q4")]
    options = calendar_quarter_options(points)
    assert options
    assert filter_by_calendar_quarters(points, []) == []


def test_narrative_vs_quant_falls_back_calendar_to_fiscal():
    data = DashboardData.from_records(
        [
            {
                "ticker": "AAPL",
                "fiscal_period": "FY2025-Q1",
                "dimension": "demand",
                "llm_level": 1.0,
                "quant_z_pit": 0.2,
                "narrative_quant_gap": 0.8,
                "any_quant_divergence": False,
            }
        ]
    )
    points = data.narrative_vs_quant(tickers=["AAPL"])
    assert len(points) == 1
    assert points[0]["calendar_quarter"] == "FY2025-Q1"
    assert points[0]["calendar_quarter_fallback"] is True
