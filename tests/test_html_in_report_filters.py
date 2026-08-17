"""In-HTML sector filters, URL wiring, Spearman parity, no Streamlit Rank IC sub."""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

import pytest

from services.earnings_monitor.dashboard.report_static import (
    html_report_filter_args,
    static_report_url,
)
from services.earnings_monitor.dashboard.sectors import ALL_COMPANIES, CUSTOM_LIST

REPO = Path(__file__).resolve().parents[1]
SN = REPO / "Structured Narrative"


def _load_sn_module(name: str, filename: str):
    path = SN / filename
    if str(SN) not in sys.path:
        sys.path.insert(0, str(SN))
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_load_sector_presets_intersects_universe(tmp_path: Path) -> None:
    presets_mod = _load_sn_module("html_filter_presets", "html_filter_presets.py")
    sectors = tmp_path / "sectors"
    sectors.mkdir()
    (sectors / "xlk_tech.txt").write_text("AAPL\nMSFT\nZZZ\n", encoding="utf-8")
    (sectors / "emptyish.txt").write_text("# comment\nNONE\n", encoding="utf-8")
    out = presets_mod.load_sector_presets(
        ("aapl", "MSFT", "NVDA"),
        sectors_dir=sectors,
    )
    assert out["xlk_tech"] == ["AAPL", "MSFT"]
    assert "emptyish" not in out


def test_spearman_rank_ic_known_vector() -> None:
    spearman_mod = _load_sn_module("spearman_ic", "spearman_ic.py")
    xs = (1.0, 2.0, 3.0, 4.0)
    ys = (10.0, 20.0, 30.0, 40.0)
    assert spearman_mod.spearman_rank_ic(xs, ys) == pytest.approx(1.0)
    assert spearman_mod.spearman_rank_ic(xs, (40.0, 30.0, 20.0, 10.0)) == pytest.approx(-1.0)
    assert spearman_mod.spearman_rank_ic((1.0, 2.0), (3.0, 4.0)) is None
    assert spearman_mod.spearman_rank_ic((1.0, 1.0, 1.0), (2.0, 3.0, 4.0)) is None


def test_static_report_url_preset_and_plain() -> None:
    plain = static_report_url("narrative_signal_eval.html")
    assert plain == "/app/static/reports/narrative_signal_eval.html"
    assert "?" not in plain
    preset = static_report_url("narrative_signal_eval.html", preset="xlk_tech")
    assert preset.endswith("?preset=xlk_tech")
    both = static_report_url(
        "consolidated_feature_panel.html",
        tickers="AAPL",
        preset="mega_cap_tech",
    )
    assert "preset=mega_cap_tech" in both
    assert "tickers=" in both


def test_html_report_filter_args_sidebar_mapping() -> None:
    available = ["AAPL", "MSFT", "NVDA"]
    assert html_report_filter_args(ALL_COMPANIES, available, available) == (None, None)
    assert html_report_filter_args("xlk_tech", ["AAPL", "MSFT"], available) == (
        None,
        "xlk_tech",
    )
    tickers, preset = html_report_filter_args(CUSTOM_LIST, ["MSFT", "AAPL"], available)
    assert preset is None
    assert tickers == ["MSFT", "AAPL"]


def test_dashboard_views_have_no_rank_ic_substitute() -> None:
    views_path = REPO / "services" / "earnings_monitor" / "dashboard" / "views.py"
    source = views_path.read_text(encoding="utf-8")
    assert "_render_filtered_rank_ic" not in source
    assert "filtered_iframe_bridge" not in source
    tree = ast.parse(source)
    names = [node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
    assert "render_signal_research" not in names


def test_rank_ic_html_contains_recompute_and_presets() -> None:
    rank_mod = _load_sn_module("rank_ic_html", "rank_ic_html.py")
    report = {
        "generated_at": "2026-08-04T00:00:00+00:00",
        "tickers": ["AAPL", "MSFT", "NVDA"],
        "horizons": ["0_56"],
        "horizon_windows": {"0_56": "T+7 to T+63"},
        "primary_label_key": "asof",
        "primary_horizon": "0_56",
        "leaderboard": [
            {
                "signal": "llm_level",
                "label": "asof",
                "horizon": "0_56",
                "dimension": "demand",
                "rank_ic_mean": 0.1,
            }
        ],
        "jackknife": [],
        "agreement_effect": [],
        "by_label": {
            "asof": {
                "0_56": {
                    "llm_level": {
                        "by_dimension": {},
                        "dimension_mean": {},
                    }
                }
            }
        },
    }
    html = rank_mod.build_rank_ic_report_html(
        report,
        period_ics=[],
        company_period=[
            {
                "label_key": "asof",
                "horizon": "0_56",
                "ticker": "AAPL",
                "period": "2025-Q1",
                "signal": "llm_level",
                "dimension": "demand",
                "signal_mean": 1.0,
                "label_mean": 0.01,
                "n": 1,
            }
        ],
    )
    assert "SECTOR_PRESETS" in html
    assert "RANK_IC_CLIENT_RECOMPUTE" in html
    assert "Rank IC recomputed for" in html
    assert "company-filter" in html
    assert "spearmanRankIC" in html
    assert 'data-jk-mode="book"' in html
    assert 'data-jk-mode="selection"' in html
    assert "Book influence" in html
    assert "Selection robustness" in html
    assert "Δ vs baseline" in html
    assert "recomputeSelectionJackknife" in html
    assert "renderBookJackknife" in html
    assert "renderSelectionJackknife" in html
    assert "syncJackknifeModeFromUniverse" in html


def test_selection_jackknife_summary_delta_parity() -> None:
    rank_mod = _load_sn_module("rank_ic_html", "rank_ic_html.py")
    # Perfect positive cross-section for AAPL/MSFT/NVDA; holding out NVDA
    # (highest signal) flips ranks enough that fold IC stays defined.
    company_period = []
    for period, base in (("2025-Q1", 0.0), ("2025-Q2", 1.0)):
        for ticker, sig, lab in (
            ("AAPL", 1.0 + base, 0.01 + base * 0.01),
            ("MSFT", 2.0 + base, 0.02 + base * 0.01),
            ("NVDA", 3.0 + base, 0.03 + base * 0.01),
            ("META", 4.0 + base, -0.04 - base * 0.01),  # flips when included
        ):
            company_period.append(
                {
                    "label_key": "asof",
                    "horizon": "0_56",
                    "ticker": ticker,
                    "period": period,
                    "signal": "llm_level",
                    "dimension": "demand",
                    "signal_mean": sig,
                    "label_mean": lab,
                    "n": 1,
                }
            )
    peer = ["AAPL", "MSFT", "NVDA"]
    out = rank_mod.selection_jackknife_summary(
        company_period,
        peer,
        label_key="asof",
        horizon="0_56",
        dimension="demand",
        signal="llm_level",
    )
    assert out["too_small"] is False
    assert out["baseline"]["n_periods"] == 2
    assert out["baseline"]["rank_ic_mean"] == pytest.approx(1.0)
    assert len(out["rows"]) == 3
    by_held = {row["held_out_ticker"]: row for row in out["rows"]}
    # Holding out any of three perfectly ranked names leaves n=2 < 3 → no periods.
    for ticker in peer:
        assert by_held[ticker]["n_periods"] == 0
        assert by_held[ticker]["delta"] is None

    four = rank_mod.selection_jackknife_summary(
        company_period,
        ["AAPL", "MSFT", "NVDA", "META"],
        label_key="asof",
        horizon="0_56",
        dimension="demand",
        signal="llm_level",
    )
    assert four["baseline"]["n_periods"] == 2
    assert four["baseline"]["rank_ic_mean"] is not None
    meta_row = next(r for r in four["rows"] if r["held_out_ticker"] == "META")
    # Dropping the disagreeing name restores perfect +1 IC.
    assert meta_row["rank_ic_mean"] == pytest.approx(1.0)
    assert meta_row["delta"] == pytest.approx(
        1.0 - float(four["baseline"]["rank_ic_mean"])
    )

    tiny = rank_mod.selection_jackknife_summary(
        company_period,
        ["AAPL", "MSFT"],
        label_key="asof",
        horizon="0_56",
        dimension="demand",
        signal="llm_level",
    )
    assert tiny["too_small"] is True
    assert tiny["rows"] == []


def test_consolidated_html_contains_sector_presets() -> None:
    import pandas as pd

    if str(SN) not in sys.path:
        sys.path.insert(0, str(SN))
    from panel_html import EvidenceLookups, build_consolidated_html
    from dimension_order import prepare_consolidated_panel
    from tests.test_consolidated_panel_report import _sample_panel

    stacked = pd.concat(
        [
            _sample_panel("AAA", "FY2025-Q1"),
            _sample_panel("BBB", "FY2025-Q1"),
        ],
        ignore_index=True,
    )
    stacked = prepare_consolidated_panel(stacked)
    empty = EvidenceLookups(level={}, delta={}, surprise={})
    html = build_consolidated_html(
        stacked,
        {"AAA": empty, "BBB": empty},
        tickers=["AAA", "BBB"],
        period_buckets=["2025-Q1"],
        default_bucket="2025-Q1",
        sector_label=None,
        generated_at="2026-08-04T00:00:00Z",
    )
    assert "SECTOR_PRESETS" in html
    assert "company-filter" in html and "cf-all" in html and "cf-none" in html
    assert "URLSearchParams" in html
    assert "data-preset=" in html
