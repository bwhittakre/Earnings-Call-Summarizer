"""Roz ticker book integration for Onboard / First-Print / research-regen."""

from __future__ import annotations

from pathlib import Path

from services.earnings_monitor.config import MonitorConfig
from services.earnings_monitor.state import OperationalState
from services.earnings_monitor.ticker_book import (
    ensure_ticker_in_book,
    load_sector_tickers,
    resolve_book_tickers,
    seed_book_if_empty,
    upsert_env_tickers,
    write_sector_ticker,
)


def _config(tmp_path: Path, **overrides) -> MonitorConfig:
    values = {
        "repo_root": tmp_path,
        "database_path": tmp_path / "state.sqlite3",
        "inbox_path": tmp_path / "inbox",
        "tickers": ("AAPL", "MSFT"),
        "research_sector": "xlk_tech",
    }
    values.update(overrides)
    return MonitorConfig(**values)


def test_write_sector_ticker_appends_once(tmp_path: Path):
    path = tmp_path / "config" / "sectors" / "xlk_tech.txt"
    path.parent.mkdir(parents=True)
    path.write_text("# book\nAAPL\nMSFT\n", encoding="utf-8")
    assert write_sector_ticker(path, "SPCX") is True
    assert write_sector_ticker(path, "spcx") is False
    assert load_sector_tickers(path) == ["AAPL", "MSFT", "SPCX"]


def test_upsert_env_tickers(tmp_path: Path):
    env_path = tmp_path / ".env.sim.local"
    env_path.write_text(
        "EARNINGS_MONITOR_TICKERS=AAPL,MSFT\nOTHER=1\n",
        encoding="utf-8",
    )
    assert upsert_env_tickers(env_path, "SPCX") is True
    assert upsert_env_tickers(env_path, "SPCX") is False
    text = env_path.read_text(encoding="utf-8")
    assert "EARNINGS_MONITOR_TICKERS=AAPL,MSFT,SPCX" in text


def test_ensure_ticker_in_book_updates_meta_sector_env(tmp_path: Path, monkeypatch):
    sector = tmp_path / "config" / "sectors" / "xlk_tech.txt"
    sector.parent.mkdir(parents=True)
    sector.write_text("AAPL\nMSFT\n", encoding="utf-8")
    env_path = tmp_path / "services" / "earnings_monitor" / ".env.sim.local"
    env_path.parent.mkdir(parents=True)
    env_path.write_text("EARNINGS_MONITOR_TICKERS=AAPL,MSFT\n", encoding="utf-8")
    monkeypatch.setenv("EARNINGS_MONITOR_TICKER_ENV_FILE", str(env_path))

    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    config = _config(tmp_path)
    result = ensure_ticker_in_book(
        ticker="SPCX",
        config=config,
        state=state,
        seed_tickers=config.tickers,
    )
    assert result.added is True
    assert "SPCX" in result.tickers
    assert result.sector_updated is True
    assert result.env_updated is True
    assert result.meta_updated is True
    assert "SPCX" in resolve_book_tickers(config, state)
    assert "SPCX" in load_sector_tickers(sector)


def test_seed_book_if_empty_then_resolve(tmp_path: Path):
    sector = tmp_path / "config" / "sectors" / "xlk_tech.txt"
    sector.parent.mkdir(parents=True)
    sector.write_text("AAPL\nNVDA\n", encoding="utf-8")
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    config = _config(tmp_path, tickers=("AAPL", "MSFT"))
    seeded = seed_book_if_empty(config, state)
    assert "AAPL" in seeded and "MSFT" in seeded and "NVDA" in seeded
    again = seed_book_if_empty(config, state)
    assert again == seeded
