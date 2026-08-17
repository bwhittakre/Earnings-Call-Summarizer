"""Tests for Custom List, HTML ticker URLs, and Quartr watchlist sync helpers."""

from __future__ import annotations

from pathlib import Path

from services.earnings_monitor.dashboard.quartr_watchlists import (
    QuartrWatchlistClient,
    company_to_ticker,
    slugify_watchlist_name,
    sync_quartr_watchlists,
    write_watchlist_sector_file,
)
from services.earnings_monitor.dashboard.report_static import static_report_url
from services.earnings_monitor.dashboard.research_data import filter_rank_ic_rows
from services.earnings_monitor.dashboard.sectors import (
    ALL_COMPANIES,
    CUSTOM_LIST,
    is_full_universe,
    list_sector_options,
    resolve_active_universe,
    sector_option_label,
)
from services.earnings_monitor.latest_onboard import LatestOnboardResult


def test_list_sector_options_includes_custom(tmp_path: Path):
    sectors = tmp_path / "sectors"
    sectors.mkdir()
    (sectors / "xlk_tech.txt").write_text("AAPL\nMSFT\n", encoding="utf-8")
    options = list_sector_options(sectors_dir=sectors)
    assert options[0] == ALL_COMPANIES
    assert options[1] == CUSTOM_LIST
    assert "xlk_tech" in options


def test_resolve_custom_list_and_full_universe():
    available = ["AAPL", "MSFT", "NVDA"]
    custom = resolve_active_universe(
        CUSTOM_LIST, available, custom_tickers=["msft", "ZZZ"]
    )
    assert custom == ["MSFT"]
    assert is_full_universe(available, available)
    assert not is_full_universe(["AAPL"], available)


def test_sector_option_label_quartr():
    assert sector_option_label("quartr_roz_expansion_v2").startswith("Quartr:")


def test_static_report_url_tickers_query():
    url = static_report_url("consolidated_feature_panel.html", tickers=["msft", "AAPL"])
    assert url.startswith("/app/static/reports/consolidated_feature_panel.html?")
    assert "tickers=" in url
    assert "AAPL" in url and "MSFT" in url


def test_static_report_url_preset_query():
    url = static_report_url("narrative_signal_eval.html", preset="xlk_tech")
    assert url == "/app/static/reports/narrative_signal_eval.html?preset=xlk_tech"


def test_filter_rank_ic_rows_by_ticker():
    rows = [
        {"ticker": "AAPL", "signal": "x", "rank_ic": 0.1},
        {"ticker": "MSFT", "signal": "x", "rank_ic": 0.2},
        {"signal": "x", "rank_ic": 0.3},  # aggregate
    ]
    filtered = filter_rank_ic_rows(rows, tickers=["AAPL"])
    assert [r.get("ticker") for r in filtered] == ["AAPL", None]


def test_slugify_and_write_watchlist_file(tmp_path: Path):
    stem = slugify_watchlist_name("Roz Expansion V2", 26369)
    assert stem.startswith("quartr_")
    path = write_watchlist_sector_file(
        tmp_path,
        stem=stem,
        tickers=["SPCX", "AAPL"],
        watchlist_id=26369,
        watchlist_name="Roz Expansion V2",
        synced_at="2026-08-04T00:00:00+00:00",
    )
    text = path.read_text(encoding="utf-8")
    assert "SPCX" in text and "AAPL" in text


def test_sync_quartr_watchlists_mocked(tmp_path: Path):
    payloads = {
        "/public/v3/watchlists": {
            "data": [{"id": 1, "name": "Test List", "companyCount": 2}]
        },
        "/public/v3/watchlists/1": {
            "data": {
                "id": 1,
                "name": "Test List",
                "companies": [
                    {"ticker": "AAPL"},
                    {"companyId": 99},
                ],
            }
        },
        "/public/v3/companies/99": {"data": {"id": 99, "ticker": "NEWCO"}},
    }

    def fake_get(url: str, headers):
        # Longest path first so /watchlists/1 does not match /watchlists.
        for path, payload in sorted(payloads.items(), key=lambda kv: -len(kv[0])):
            if url.endswith(path) or path in url:
                return payload
        raise AssertionError(url)

    client = QuartrWatchlistClient(api_key="test", http_get=fake_get)
    onboarded: list[str] = []

    def fake_onboard(**kwargs):
        ticker = kwargs["ticker"]
        onboarded.append(ticker)
        return LatestOnboardResult(ticker=ticker, status="latest_call_onboarded")

    result = sync_quartr_watchlists(
        sectors_dir=tmp_path,
        repo_root=tmp_path,
        available_tickers=["AAPL"],
        force=True,
        micro_onboard=True,
        client=client,
        onboard_fn=fake_onboard,
    )
    assert result.error is None
    assert result.watchlists == 1
    assert any(path.startswith("quartr_") for path in result.files_written)
    assert onboarded == ["NEWCO"]
    assert "NEWCO" in result.micro_onboarded


def test_company_to_ticker_from_nested():
    client = QuartrWatchlistClient(api_key="x", http_get=lambda u, h: {})
    assert (
        company_to_ticker({"company": {"ticker": "txn"}}, client=client) == "TXN"
    )
