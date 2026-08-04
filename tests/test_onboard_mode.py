"""Unit tests for Onboard lookback, mode classification, and Quartr path formatting."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SN = REPO / "Structured Narrative"
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
if str(SN) not in sys.path:
    sys.path.insert(0, str(SN))

from services.earnings_monitor.mode_router import (  # noqa: E402
    choose_lookback_years,
    classify_workflow_mode,
)
from services.earnings_monitor.onboard import (  # noqa: E402
    OnboardBlocked,
    allowlist_guidance,
    run_onboard,
    scaffold_quarters_from_periods,
)
from quartr_history_import import (  # noqa: E402
    format_transcript_path,
    normalize_fiscal_period,
)


UTC = timezone.utc


def test_choose_lookback_years_long_when_report_48h_away():
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    report = now + timedelta(hours=48)
    assert choose_lookback_years(report, now=now) == 10
    assert choose_lookback_years(report + timedelta(minutes=1), now=now) == 10


def test_choose_lookback_years_short_inside_48h():
    now = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    report = now + timedelta(hours=47, minutes=59)
    assert choose_lookback_years(report, now=now) == 3
    assert choose_lookback_years(now - timedelta(hours=1), now=now) == 3


def test_classify_first_print_when_zero_history():
    decision = classify_workflow_mode(
        prior_event_count=0,
        on_disk_transcript_count=0,
    )
    assert decision.mode == "first_print"
    assert "First-Print" in decision.reason


def test_classify_onboard_when_prior_events_without_registry():
    decision = classify_workflow_mode(
        prior_event_count=12,
        on_disk_transcript_count=0,
        in_company_registry=False,
        has_scored_history=False,
    )
    assert decision.mode == "onboard"


def test_classify_standard_when_registered_with_history():
    decision = classify_workflow_mode(
        prior_event_count=8,
        on_disk_transcript_count=20,
        in_company_registry=True,
        has_scored_history=True,
    )
    assert decision.mode == "standard"


def test_classify_onboard_for_disk_only_without_provider_events():
    decision = classify_workflow_mode(
        prior_event_count=0,
        on_disk_transcript_count=4,
        in_company_registry=False,
    )
    assert decision.mode == "onboard"


def test_format_transcript_path_flat_and_nested(tmp_path: Path):
    flat = format_transcript_path(tmp_path, "amzn", "FY2024-Q1", layout="flat")
    nested = format_transcript_path(tmp_path, "amzn", "FY2024-Q1", layout="nested")
    assert flat == tmp_path / "AMZN_FY2024-Q1.txt"
    assert nested == tmp_path / "AMZN" / "FY2024-Q1.txt"
    with pytest.raises(ValueError):
        format_transcript_path(tmp_path, "AMZN", "2024Q1", layout="flat")
    with pytest.raises(ValueError):
        format_transcript_path(tmp_path, "AMZN", "FY2024-Q1", layout="sideways")


def test_normalize_fiscal_period_from_quartr_fields():
    assert (
        normalize_fiscal_period(fiscal_year=2024, fiscal_period="Q2") == "FY2024-Q2"
    )
    assert normalize_fiscal_period(fiscal_period="FY2025-Q3") == "FY2025-Q3"
    assert (
        normalize_fiscal_period(fiscal_year=2026, title="Q1 2026 Earnings Call")
        == "FY2026-Q1"
    )


def test_scaffold_quarters_earliest_is_prior():
    prior, output = scaffold_quarters_from_periods(
        ["FY2024-Q2", "FY2024-Q1", "FY2024-Q3"],
        target_period="FY2024-Q4",
    )
    assert prior == ["FY2024-Q1"]
    assert output == ["FY2024-Q2", "FY2024-Q3", "FY2024-Q4"]


def test_allowlist_guidance_mentions_ticker():
    note = allowlist_guidance("NEWCO", ["AMZN", "MSFT"])
    assert "NEWCO" in note
    assert "EARNINGS_MONITOR_TICKERS=" in note


def test_run_onboard_first_print_fallthrough(tmp_path: Path):
    report = datetime(2026, 9, 1, tzinfo=UTC)
    result = run_onboard(
        repo_root=tmp_path,
        ticker="ZZZZ",
        fiscal_period="FY2026-Q2",
        report_at=report,
        now=report - timedelta(days=10),
        prior_event_count=0,
        dry_run=True,
        skip_pull=True,
        skip_ids=True,
        skip_fiscal=True,
        skip_quant=True,
        skip_llm=True,
        skip_panel=True,
    )
    assert result.status == "first_print_fallback"
    assert result.mode == "first_print"
    assert result.error and "FIRST-PRINT" in result.error


def test_run_onboard_blocks_after_report_at(tmp_path: Path):
    raw = tmp_path / "Structured Narrative" / "transcripts_raw"
    raw.mkdir(parents=True)
    (raw / "ACME_FY2025-Q1.txt").write_text("body\n", encoding="utf-8")
    (raw / "ACME_FY2025-Q2.txt").write_text("body\n", encoding="utf-8")
    report = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    result = run_onboard(
        repo_root=tmp_path,
        ticker="ACME",
        fiscal_period="FY2026-Q2",
        report_at=report,
        now=report,  # at/after deadline
        prior_event_count=5,
        dry_run=True,
        skip_pull=True,
        skip_ids=True,
        skip_fiscal=True,
        skip_quant=True,
        skip_llm=True,
        skip_panel=True,
        force_mode="onboard",
    )
    assert result.status == "onboarding_blocked"
    assert result.error
    assert "report_at" in result.error or "blocked" in result.error.lower()


def test_run_onboard_dry_run_completes_with_mock_commands(tmp_path: Path):
    raw = tmp_path / "Structured Narrative" / "transcripts_raw"
    raw.mkdir(parents=True)
    (raw / "ACME_FY2024-Q4.txt").write_text("prior\n", encoding="utf-8")
    (raw / "ACME_FY2025-Q1.txt").write_text("out\n", encoding="utf-8")
    (tmp_path / "config").mkdir(parents=True)
    report = datetime(2026, 9, 1, tzinfo=UTC)

    def fake_run(argv, *, cwd, dry_run, env=None):
        return {"argv": list(argv), "cwd": str(cwd), "dry_run": dry_run, "returncode": 0}

    result = run_onboard(
        repo_root=tmp_path,
        ticker="ACME",
        fiscal_period="FY2025-Q2",
        report_at=report,
        now=report - timedelta(days=10),
        prior_event_count=4,
        dry_run=True,
        skip_pull=True,
        skip_ids=True,
        skip_fiscal=False,
        skip_quant=True,
        skip_llm=True,
        skip_panel=True,
        force_mode="onboard",
        configured_tickers=["AMZN"],
        run_command=fake_run,
    )
    assert result.status == "completed"
    assert result.prior_quarters == ["FY2024-Q4"]
    assert "FY2025-Q1" in result.output_quarters
    assert "ACME" in result.allowlist_guidance
    assert not isinstance(result.error, OnboardBlocked)
