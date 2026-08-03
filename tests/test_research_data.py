"""Tests for Rank IC / consolidated research loaders and HTML report resolution."""

from __future__ import annotations

from pathlib import Path

from services.earnings_monitor.dashboard.research_data import (
    can_inline_html,
    html_report_meta,
    load_consolidated_panel,
    load_rank_ic_bundle,
    resolve_consolidated_html,
    resolve_cross_company_root,
    resolve_rank_ic_html,
    resolve_report_html,
)
from services.earnings_monitor.dashboard.views import (
    VIEWS,
    render_consolidated_panel,
    render_signal_research,
)


class _FakeSt:
    def __init__(self) -> None:
        self.info_messages: list[str] = []
        self.captions: list[str] = []
        self.headers: list[str] = []
        self.html_calls = 0

    def header(self, text: str) -> None:
        self.headers.append(text)

    def caption(self, text: str) -> None:
        self.captions.append(text)

    def info(self, text: str) -> None:
        self.info_messages.append(text)

    def warning(self, text: str) -> None:
        self.info_messages.append(text)


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


def test_resolve_report_html_prefers_full_consolidated(tmp_path: Path) -> None:
    cross = tmp_path / "output" / "cross_company"
    reports = cross / "reports"
    reports.mkdir(parents=True)
    small = reports / "narrative_signal_eval.html"
    small.write_text("<html><body>ok</body></html>", encoding="utf-8")
    huge = reports / "consolidated_feature_panel.html"
    huge.write_bytes(b"x" * 2000)
    medium = reports / "cross_section_panel.html"
    medium.write_text("<html><body>panel</body></html>", encoding="utf-8")

    assert resolve_report_html(
        "narrative_signal_eval", history_source=tmp_path / "output"
    ) == small
    # Prefer the full consolidated report even when large; do not fall back.
    assert resolve_consolidated_html(history_source=tmp_path / "output") == huge
    assert (
        resolve_report_html(
            "consolidated_feature_panel",
            history_source=tmp_path / "output",
            max_bytes=500,
        )
        is None
    )
    assert can_inline_html(small)
    assert resolve_rank_ic_html(history_source=tmp_path / "output") == small
    meta = html_report_meta(small)
    assert meta["stem"] == "narrative_signal_eval"
    assert meta["generated_at"]


def test_signal_research_empty_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EARNINGS_MONITOR_HISTORY_SOURCE", str(tmp_path / "missing"))
    fake = _FakeSt()
    render_signal_research(fake, data=None)  # type: ignore[arg-type]
    assert fake.info_messages
    assert "Rank IC HTML" in fake.info_messages[0] or "not found" in fake.info_messages[0].lower()


def test_consolidated_empty_state(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("EARNINGS_MONITOR_HISTORY_SOURCE", str(tmp_path / "missing"))
    fake = _FakeSt()
    render_consolidated_panel(fake, data=None)  # type: ignore[arg-type]
    assert fake.info_messages
    assert "Consolidated" in fake.info_messages[0]
