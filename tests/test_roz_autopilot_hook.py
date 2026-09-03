"""Tests for the desk autopilot hook wired into Roz earnings monitor.

All tests are fixture-based — no real LLM calls, no disk I/O to real paths,
no subprocess, no network.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

REPO_ROOT = Path("/fake/repo/root")


def _make_fake_scripts(monkeypatch, gold_tickers=("GLD",), run_for_ticker_return=None):
    """Inject fake script modules into sys.modules so desk_autopilot imports succeed."""
    if run_for_ticker_return is None:
        run_for_ticker_return = {"seeds_inserted_confirmed": 1}

    fake_autopilot = MagicMock()
    fake_autopilot.run_for_ticker.return_value = dict(run_for_ticker_return)

    fake_overlay = MagicMock()
    fake_overlay.load_overlay.return_value = {"schema_version": "1", "trees": []}

    fake_retrieval = MagicMock()
    fake_retrieval.GOLD_TICKERS = set(gold_tickers)

    fake_ops_catalogs = MagicMock()
    fake_ops_catalogs.OPS_TREES = {}

    fake_hc_catalogs = MagicMock()
    fake_hc_catalogs.HC_TREES = {}

    fake_ops = MagicMock()
    fake_ops.TECH_TICKERS = set()

    monkeypatch.setitem(sys.modules, "scripts._desk_autopilot", fake_autopilot)
    monkeypatch.setitem(sys.modules, "scripts._desk_catalog_overlay", fake_overlay)
    monkeypatch.setitem(sys.modules, "scripts._desk_retrieval", fake_retrieval)
    monkeypatch.setitem(sys.modules, "scripts._desk_trees_v2_catalogs", fake_ops_catalogs)
    monkeypatch.setitem(sys.modules, "scripts._desk_trees_v2_hc_catalogs", fake_hc_catalogs)
    monkeypatch.setitem(sys.modules, "scripts._desk_trees_v2_ops", fake_ops)

    return fake_autopilot


# ---------------------------------------------------------------------------
# Tests for run_autopilot_for_ticker
# ---------------------------------------------------------------------------


def test_kill_switch_returns_skipped(monkeypatch, tmp_path):
    """DESK_AUTOPILOT=0 → {"status": "skipped", "reason": "kill_switch"}."""
    monkeypatch.setenv("DESK_AUTOPILOT", "0")

    from services.earnings_monitor.desk_autopilot import run_autopilot_for_ticker

    result = run_autopilot_for_ticker(
        repo_root=tmp_path,
        ticker="AAPL",
        fiscal_period="2025-Q1",
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "kill_switch"


def test_gold_ticker_returns_skipped(monkeypatch, tmp_path):
    """A gold ticker → {"status": "skipped", "reason": "gold_ticker"}."""
    monkeypatch.delenv("DESK_AUTOPILOT", raising=False)
    _make_fake_scripts(monkeypatch, gold_tickers=("NVDA",))

    from services.earnings_monitor import desk_autopilot as _mod
    import importlib
    importlib.reload(_mod)

    result = _mod.run_autopilot_for_ticker(
        repo_root=tmp_path,
        ticker="NVDA",
        fiscal_period="2025-Q2",
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "gold_ticker"


def test_run_for_ticker_called_with_right_args(monkeypatch, tmp_path):
    """When enabled and ticker is not gold, run_for_ticker is called correctly."""
    monkeypatch.delenv("DESK_AUTOPILOT", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    fake_autopilot = _make_fake_scripts(
        monkeypatch,
        gold_tickers=set(),
        run_for_ticker_return={"seeds_inserted_confirmed": 1},
    )

    from services.earnings_monitor import desk_autopilot as _mod
    import importlib
    importlib.reload(_mod)

    result = _mod.run_autopilot_for_ticker(
        repo_root=tmp_path,
        ticker="MSFT",
        fiscal_period="2025-Q1",
        budget_usd=2.5,
    )

    assert result["status"] == "ok"
    assert result["seeds_inserted_confirmed"] == 1

    call_args = fake_autopilot.run_for_ticker.call_args
    assert call_args[0][0] == "MSFT"
    assert call_args[1]["budget_usd"] == 2.5


def test_run_for_ticker_exception_returns_error(monkeypatch, tmp_path):
    """If run_for_ticker raises, returns {"status": "error"} without re-raising."""
    monkeypatch.delenv("DESK_AUTOPILOT", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    fake_autopilot = _make_fake_scripts(monkeypatch, gold_tickers=set())
    fake_autopilot.run_for_ticker.side_effect = RuntimeError("boom")

    from services.earnings_monitor import desk_autopilot as _mod
    import importlib
    importlib.reload(_mod)

    # Must not raise
    result = _mod.run_autopilot_for_ticker(
        repo_root=tmp_path,
        ticker="AMD",
        fiscal_period="2025-Q1",
    )

    assert result["status"] == "error"
    assert "boom" in result["reason"]


# ---------------------------------------------------------------------------
# Tests for MonitorConfig
# ---------------------------------------------------------------------------


def test_monitor_config_desk_autopilot_defaults():
    """desk_autopilot_after_post_call defaults to True, budget defaults to 1.0."""
    from services.earnings_monitor.config import MonitorConfig

    cfg = MonitorConfig(
        repo_root=Path("/fake"),
        database_path=Path("/fake/monitor.sqlite3"),
        inbox_path=Path("/fake/inbox"),
    )

    assert cfg.desk_autopilot_after_post_call is True
    assert cfg.desk_autopilot_budget_usd == 1.0


def test_monitor_config_from_env_desk_autopilot_disabled(tmp_path):
    """EARNINGS_MONITOR_DESK_AUTOPILOT=0 parses to False."""
    from services.earnings_monitor.config import MonitorConfig

    env = {
        "EARNINGS_MONITOR_REPO_ROOT": str(tmp_path),
        "EARNINGS_MONITOR_DESK_AUTOPILOT": "0",
    }
    cfg = MonitorConfig.from_env(env, repo_root=tmp_path)

    assert cfg.desk_autopilot_after_post_call is False


def test_monitor_config_from_env_budget_usd(tmp_path):
    """EARNINGS_MONITOR_DESK_AUTOPILOT_BUDGET_USD=2.5 parses to 2.5."""
    from services.earnings_monitor.config import MonitorConfig

    env = {
        "EARNINGS_MONITOR_REPO_ROOT": str(tmp_path),
        "EARNINGS_MONITOR_DESK_AUTOPILOT_BUDGET_USD": "2.5",
    }
    cfg = MonitorConfig.from_env(env, repo_root=tmp_path)

    assert cfg.desk_autopilot_budget_usd == pytest.approx(2.5)
