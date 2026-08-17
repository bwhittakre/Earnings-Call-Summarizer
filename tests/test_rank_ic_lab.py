"""Tests for Rank IC Lab blend, recipe store, and page isolation."""
from __future__ import annotations

from pathlib import Path

import pytest

from services.earnings_monitor.dashboard.lab_store import (
    LabStoreError,
    append_trial,
    empty_store,
    get_recipe,
    load_lab_store,
    recipes_for,
    save_lab_store,
    trials_for,
    universe_key,
    upsert_recipe,
)
from services.earnings_monitor.dashboard.rank_ic_lab import (
    CALL_DATE_SIGNALS,
    LAB_BLEND_SIGNAL,
    blend_company_period,
    compact_stats,
    evaluate_lab_recipe,
)
from services.earnings_monitor.dashboard.rank_ic_research import RANK_IC_VIEWS
from services.earnings_monitor.dashboard.research_data import import_sn
from services.earnings_monitor.dashboard.sectors import ALL_COMPANIES, CUSTOM_LIST
from services.earnings_monitor.dashboard.views import RANK_IC_VIEWS as VIEWS_EXPORT
from services.earnings_monitor.dashboard.views import VIEWS

DASHBOARD_DIR = (
    Path(__file__).resolve().parents[1]
    / "services"
    / "earnings_monitor"
    / "dashboard"
)

TICKERS = ["AAA", "BBB", "CCC", "DDD"]
PERIODS = [f"2024-Q{q}" for q in range(1, 5)] + ["2025-Q1", "2025-Q2"]
ROZ_VIEWS = (
    "Overview",
    "Event inbox",
    "Company history",
    "Dimension panel",
    "Cross-company",
    "Narrative vs quant",
    "Book ranks",
    "Consolidated panel",
    "Operations",
    "Audit",
)
RESEARCH_VIEWS = (
    "Period heatmap",
    "Company × quarter",
    "Leaderboard",
    "By dimension",
    "Agreement effect",
    "Jackknife",
    "Quarter drivers",
    "Measure drill-down",
    "Horizon fingerprint",
    "Street overlay",
)


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


def _aligned_book(*, constant_signal: str = "change_magnitude") -> list[dict]:
    """6 periods × 4 names. llm_level ranks with returns; constant_signal is 999."""
    rows: list[dict] = []
    for period in PERIODS:
        for rank, ticker in enumerate(TICKERS, start=1):
            ret = 0.01 * rank
            rows.append(_cell(ticker, period, float(rank), ret, signal="llm_level"))
            rows.append(_cell(ticker, period, 0.1 * rank, ret, signal="quant_z_pit"))
            rows.append(_cell(ticker, period, 999.0, ret, signal=constant_signal))
    return rows


def test_blend_parity_matches_helper_spearman() -> None:
    company_period = _aligned_book()
    lab_rows = blend_company_period(
        company_period,
        TICKERS,
        label="asof",
        horizon="0_56",
        dimension="demand",
        weights={"llm_level": 1.0},
    )
    assert lab_rows
    assert all(row["signal"] == LAB_BLEND_SIGNAL for row in lab_rows)
    html = import_sn("rank_ic_html")
    periods = sorted({str(row["period"]) for row in lab_rows})
    lab_ics = html.period_rank_ics_for_selection(
        lab_rows,
        TICKERS,
        label_key="asof",
        horizon="0_56",
        dimension="demand",
        signal=LAB_BLEND_SIGNAL,
        periods=periods,
    )
    base_ics = html.period_rank_ics_for_selection(
        company_period,
        TICKERS,
        label_key="asof",
        horizon="0_56",
        dimension="demand",
        signal="llm_level",
        periods=periods,
    )
    assert lab_ics == pytest.approx(base_ics)
    assert all(ic == pytest.approx(1.0) for ic in lab_ics if ic is not None)
    assert len(periods) >= 1


def test_constant_raw_signal_does_not_contribute() -> None:
    company_period = _aligned_book()
    only_constant = blend_company_period(
        company_period,
        TICKERS,
        label="asof",
        horizon="0_56",
        dimension="demand",
        weights={"change_magnitude": 1.0},
    )
    assert only_constant == []

    level_only = blend_company_period(
        company_period,
        TICKERS,
        label="asof",
        horizon="0_56",
        dimension="demand",
        weights={"llm_level": 1.0},
    )
    mixed = blend_company_period(
        company_period,
        TICKERS,
        label="asof",
        horizon="0_56",
        dimension="demand",
        weights={"llm_level": 1.0, "change_magnitude": 100.0},
    )
    level_by_key = {(r["ticker"], r["period"]): r["signal_mean"] for r in level_only}
    mixed_by_key = {(r["ticker"], r["period"]): r["signal_mean"] for r in mixed}
    assert mixed_by_key
    assert set(mixed_by_key) == set(level_by_key)
    for key, value in mixed_by_key.items():
        assert value == pytest.approx(level_by_key[key])


def test_lab_store_missing_is_empty_corrupt_refuses_clobber(tmp_path: Path) -> None:
    path = tmp_path / "rank_ic_lab.json"
    assert load_lab_store(path) == empty_store()
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(LabStoreError, match="unreadable"):
        load_lab_store(path)
    with pytest.raises(LabStoreError, match="unreadable"):
        save_lab_store(empty_store(), path)
    assert path.read_text(encoding="utf-8") == "{not-json"
    path.write_text("[]\n", encoding="utf-8")
    with pytest.raises(LabStoreError, match="unreadable"):
        load_lab_store(path)
    assert path.read_text(encoding="utf-8") == "[]\n"


def test_universe_key_distinguishes_sector_vs_all() -> None:
    assert universe_key(ALL_COMPANIES, ["AAPL", "MSFT"]) == "all"
    assert universe_key(None, ["AAPL"]) == "all"
    assert universe_key("xlk_tech", ["AAPL", "MSFT"]) == "xlk_tech"
    custom_ab = universe_key(CUSTOM_LIST, ["MSFT", "AAPL"])
    custom_ba = universe_key(CUSTOM_LIST, ["AAPL", "MSFT"])
    custom_other = universe_key(CUSTOM_LIST, ["NVDA"])
    assert custom_ab.startswith("custom:")
    assert custom_ab == custom_ba
    assert custom_ab != custom_other
    assert custom_ab != universe_key("xlk_tech", ["AAPL", "MSFT"])


def test_recipe_round_trip_keyed_by_universe(tmp_path: Path) -> None:
    path = tmp_path / "rank_ic_lab.json"
    store = load_lab_store(path)
    sector = upsert_recipe(
        store,
        name="equal blend",
        universe_key_value="xlk_tech",
        label="asof",
        horizon="0_56",
        dimension="demand",
        weights={"llm_level": 0.5, "quant_z_pit": 0.5},
        include_revision=False,
    )
    full = upsert_recipe(
        store,
        name="equal blend",
        universe_key_value="all",
        label="asof",
        horizon="0_56",
        dimension="guidance",
        weights={"quant_z_pit": 1.0},
        include_revision=True,
    )
    save_lab_store(store, path)
    reloaded = load_lab_store(path)
    assert sector["id"] != full["id"]
    assert [r["universe_key"] for r in recipes_for(reloaded, "xlk_tech")] == ["xlk_tech"]
    assert [r["universe_key"] for r in recipes_for(reloaded, "all")] == ["all"]
    got = get_recipe(reloaded, sector["id"])
    assert got is not None
    assert got["weights"]["llm_level"] == pytest.approx(0.5)
    assert got["dimension"] == "demand"
    again = upsert_recipe(
        reloaded,
        name="equal blend",
        universe_key_value="xlk_tech",
        label="event",
        horizon="0_14",
        dimension="margins",
        weights={"llm_level": 1.0},
        include_revision=False,
    )
    assert again["id"] == sector["id"]
    assert again["label"] == "event"


def test_log_trial_stores_lab_vs_baseline(tmp_path: Path) -> None:
    path = tmp_path / "rank_ic_lab.json"
    store = load_lab_store(path)
    recipe = upsert_recipe(
        store,
        name="quant tilt",
        universe_key_value="xlk_tech",
        label="asof",
        horizon="0_56",
        dimension="demand",
        weights={"quant_z_pit": 1.0},
        include_revision=False,
    )
    lab = compact_stats(
        {"rank_ic_mean": 0.21, "rank_ic_ir": 0.8, "positive_rank_ic_hit_rate": 0.6, "n_periods": 8},
        n_names=12,
    )
    baseline = compact_stats(
        {"rank_ic_mean": 0.10, "rank_ic_ir": 0.4, "positive_rank_ic_hit_rate": 0.5, "n_periods": 10},
        n_names=12,
        signal="quant_z_pit",
    )
    trial = append_trial(
        store,
        recipe=recipe,
        lab_stats=lab,
        baseline_stats=baseline,
        tag="good",
    )
    save_lab_store(store, path)
    logged = trials_for(load_lab_store(path), "xlk_tech")
    assert len(logged) == 1
    row = logged[0]
    assert row["id"] == trial["id"]
    assert row["tag"] == "good"
    assert row["lab"]["rank_ic_mean"] == pytest.approx(0.21)
    assert row["lab"]["n_names"] == 12
    assert row["baseline"]["rank_ic_mean"] == pytest.approx(0.10)
    assert row["baseline"]["signal"] == "quant_z_pit"
    assert row["weights"]["quant_z_pit"] == pytest.approx(1.0)


def test_evaluate_lab_recipe_scoreboard_keys() -> None:
    company_period = _aligned_book()
    result = evaluate_lab_recipe(
        company_period,
        TICKERS,
        label="asof",
        horizon="0_56",
        dimension="demand",
        weights={"llm_level": 1.0},
        baseline_signal="quant_z_pit",
    )
    assert result["lab"]["n_names"] == 4
    assert result["lab"]["n_periods"] >= 1
    assert result["lab"]["rank_ic_mean"] == pytest.approx(1.0)
    assert result["baseline"]["signal"] == "quant_z_pit"
    assert result["baseline"]["rank_ic_mean"] == pytest.approx(1.0)
    assert len(result["periods"]) == len(result["lab_period_ics"])
    assert len(result["periods"]) == len(result["baseline_period_ics"])


def test_views_untouched_and_lab_page_exists() -> None:
    assert tuple(VIEWS) == ROZ_VIEWS
    assert tuple(RANK_IC_VIEWS) == RESEARCH_VIEWS
    assert RANK_IC_VIEWS is VIEWS_EXPORT
    assert "Signal research" not in VIEWS
    page = DASHBOARD_DIR / "pages" / "2_Rank_IC_Lab.py"
    assert page.is_file()
    source = page.read_text(encoding="utf-8")
    assert "render_rank_ic_lab" in source
    assert "load_dashboard_shell" in source
    assert "render_research_status_sidebar" in source
    lab_mod = (DASHBOARD_DIR / "rank_ic_lab.py").read_text(encoding="utf-8")
    for signal in CALL_DATE_SIGNALS:
        assert signal in lab_mod
    composite = import_sn("composite_signal")
    assert CALL_DATE_SIGNALS == composite.COMPOSITE_INPUT_SIGNALS


def test_rank_ic_research_does_not_import_lab() -> None:
    source = (DASHBOARD_DIR / "rank_ic_research.py").read_text(encoding="utf-8")
    assert "from .rank_ic_lab" not in source
    assert "import rank_ic_lab" not in source
    assert "lab_store" not in source
    views = (DASHBOARD_DIR / "views.py").read_text(encoding="utf-8")
    assert "from .rank_ic_lab" not in views
    assert "lab_store" not in views
    assert "from .rank_ic_research import RANK_IC_VIEWS" in views
