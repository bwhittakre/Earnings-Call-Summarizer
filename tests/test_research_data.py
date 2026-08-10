"""Tests for Rank IC / consolidated research loaders and view registration."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.earnings_monitor.dashboard.research_data import (
    artifact_universe_status,
    filter_rank_ic_rows,
    format_universe_stale_message,
    load_consolidated_panel,
    load_rank_ic_bundle,
    resolve_cross_company_root,
    unique_sorted,
)
from services.earnings_monitor.dashboard.views import VIEWS

try:
    from services.earnings_monitor.dashboard.charts import (  # type: ignore
        rank_ic_heatmap,
        rank_ic_leaderboard_chart,
    )
except ImportError:  # Rank IC chart helpers may live elsewhere / not yet present
    rank_ic_heatmap = None  # type: ignore
    rank_ic_leaderboard_chart = None  # type: ignore


def test_views_include_research_tabs() -> None:
    assert "Signal research" in VIEWS
    assert "Consolidated panel" in VIEWS


def test_resolve_cross_company_root(tmp_path: Path) -> None:
    output = tmp_path / "output"
    cross = output / "cross_company"
    cross.mkdir(parents=True)
    assert resolve_cross_company_root(output) == cross
    assert resolve_cross_company_root(cross) == cross


def test_load_rank_ic_bundle_from_fixtures(tmp_path: Path) -> None:
    cross = tmp_path / "output" / "cross_company"
    (cross / "csv").mkdir(parents=True)
    (cross / "json").mkdir(parents=True)
    period = cross / "csv" / "narrative_signal_eval_period_ic.csv"
    board = cross / "csv" / "narrative_signal_eval_leaderboard.csv"
    period.write_text(
        "fiscal_period,dimension,signal,label,horizon,n,rank_ic,ic\n"
        "FY2024-Q1,margins,llm_level,asof,0_56,8,0.25,0.20\n"
        "FY2024-Q2,margins,llm_level,asof,0_56,8,-0.10,-0.05\n",
        encoding="utf-8",
    )
    board.write_text(
        "signal,dimension,label,horizon,rank_ic_mean,rank_ic_ir,"
        "positive_rank_ic_hit_rate,n_periods,n_rows,is_primary\n"
        "llm_level,margins,asof,0_56,0.12,0.40,0.55,10,80,true\n",
        encoding="utf-8",
    )
    (cross / "json" / "narrative_signal_eval.json").write_text(
        '{"generated_at":"2026-08-03T12:00:00","tickers":["AAPL","MSFT"]}',
        encoding="utf-8",
    )

    bundle = load_rank_ic_bundle(history_source=tmp_path / "output")
    assert bundle.available
    assert len(bundle.period_ic) == 2
    assert len(bundle.leaderboard) == 1
    assert bundle.meta["tickers"] == ["AAPL", "MSFT"]
    assert bundle.meta["generated_at"] == "2026-08-03T12:00:00"

    filtered = filter_rank_ic_rows(
        bundle.period_ic, label="asof", horizon="0_56", dimension="margins"
    )
    assert len(filtered) == 2
    assert unique_sorted(bundle.leaderboard, "signal") == ["llm_level"]


def test_load_consolidated_panel_probes_stems(tmp_path: Path) -> None:
    cross = tmp_path / "output" / "cross_company"
    (cross / "csv").mkdir(parents=True)
    spine = cross / "csv" / "cross_section_spine.csv"
    panel = cross / "csv" / "cross_section_panel.csv"
    spine.write_text(
        "ticker,fiscal_period,period_end_calendar_quarter,dimension,llm_level,quant_z_pit\n"
        "AAPL,FY2025-Q1,2025-Q1,margins,1.2,0.4\n"
        "MSFT,FY2025-Q1,2025-Q1,margins,0.8,0.1\n",
        encoding="utf-8",
    )
    panel.write_text(
        "ticker,fiscal_period,dimension,llm_level\nAAPL,FY2025-Q1,margins,1.2\n",
        encoding="utf-8",
    )

    bundle = load_consolidated_panel(history_source=tmp_path / "output")
    assert bundle.available
    assert bundle.stem == "cross_section_panel"
    assert len(bundle.spine) == 2
    assert "AAPL" in bundle.meta["tickers"]


def test_artifact_universe_status_detects_missing_csco() -> None:
    status = artifact_universe_status(
        ["AAPL", "MSFT", "CSCO"],
        {"tickers": ["AAPL", "MSFT"]},
        {"tickers": ["AAPL", "MSFT", "NVDA"]},
    )
    assert status["stale"] is True
    assert status["ok"] is False
    assert status["missing_from_rank"] == ["CSCO"]
    assert status["missing_from_consol"] == ["CSCO"]
    message = format_universe_stale_message(status)
    assert message is not None
    assert "CSCO" in message
    assert "research-regen" in message


def test_artifact_universe_status_ok_when_aligned() -> None:
    status = artifact_universe_status(
        ["AAPL", "CSCO"],
        {"tickers": ["AAPL", "CSCO", "MSFT"]},
        {"tickers": ["CSCO", "AAPL"]},
    )
    assert status["ok"] is True
    assert status["stale"] is False
    assert format_universe_stale_message(status) is None


def test_artifact_universe_status_skips_empty_artifact_meta() -> None:
    status = artifact_universe_status(["AAPL", "CSCO"], None, {"tickers": []})
    assert status["rank_available"] is False
    assert status["consol_available"] is False
    assert status["stale"] is False


@pytest.mark.skipif(
    rank_ic_heatmap is None or rank_ic_leaderboard_chart is None,
    reason="Rank IC chart helpers not exported from dashboard.charts",
)
def test_rank_ic_charts_build() -> None:
    heat = rank_ic_heatmap(
        [
            {
                "fiscal_period": "FY2024-Q1",
                "dimension": "margins",
                "signal": "llm_level",
                "label": "asof",
                "horizon": "0_56",
                "rank_ic": 0.2,
                "n": 8,
            }
        ]
    )
    assert hasattr(heat, "to_dict")
    board = rank_ic_leaderboard_chart(
        [
            {
                "signal": "llm_level",
                "dimension": "margins",
                "rank_ic_mean": 0.15,
                "rank_ic_ir": 0.5,
                "positive_rank_ic_hit_rate": 0.6,
                "n_periods": 12,
            }
        ]
    )
    assert hasattr(board, "to_dict")
