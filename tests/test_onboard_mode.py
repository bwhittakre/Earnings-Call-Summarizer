"""Unit tests for Onboard lookback, mode classification, and Quartr path formatting."""

from __future__ import annotations

import json
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
    OnboardError,
    ProviderHistoryUnavailable,
    _pull_history_transcripts,
    allowlist_guidance,
    count_prior_provider_events,
    make_quartr_event_lister,
    run_onboard,
    scaffold_quarters_from_periods,
    sync_book_after_onboard,
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


def test_count_prior_provider_events_requires_lister():
    with pytest.raises(ProviderHistoryUnavailable, match="event_lister is required"):
        count_prior_provider_events(
            ticker="CSCO",
            since=datetime(2016, 1, 1, tzinfo=UTC),
            until=datetime(2026, 8, 12, tzinfo=UTC),
            event_lister=None,
        )


def test_count_prior_provider_events_uses_mock_lister():
    def fake_lister(ticker: str, since: datetime, until: datetime) -> int:
        assert ticker == "CSCO"
        return 17

    assert (
        count_prior_provider_events(
            ticker="CSCO",
            since=datetime(2016, 1, 1, tzinfo=UTC),
            until=datetime(2026, 8, 12, tzinfo=UTC),
            event_lister=fake_lister,
        )
        == 17
    )


def test_make_quartr_event_lister_counts_fiscal_events_before_until():
    class FakeClient:
        api_key = "test-key"

        def resolve_company_id(self, ticker: str) -> int:
            assert ticker == "CSCO"
            return 4639

        def iter_events(self, *, company_id: int, start: datetime, end: datetime):
            assert company_id == 4639
            return [
                {
                    "id": 1,
                    "title": "Q3 2026",
                    "fiscalYear": "2026",
                    "fiscalPeriod": "Q3",
                    "date": "2026-05-13T20:30:00.000Z",
                },
                {
                    "id": 2,
                    "title": "Q4 2026",
                    "fiscalYear": "2026",
                    "fiscalPeriod": "Q4",
                    "date": "2026-08-12T20:30:00.000Z",
                },
                {
                    "id": 3,
                    "title": "Investor Day",
                    "date": "2026-04-01T12:00:00.000Z",
                },
            ]

    lister = make_quartr_event_lister(REPO, client=FakeClient())
    # until == Q4 call time → Q4 excluded; Investor Day has no fiscal period
    assert (
        lister(
            "CSCO",
            datetime(2016, 1, 1, tzinfo=UTC),
            datetime(2026, 8, 12, 20, 30, tzinfo=UTC),
        )
        == 1
    )


def test_run_onboard_uses_event_lister_without_force(tmp_path: Path):
    report = datetime(2026, 9, 1, tzinfo=UTC)

    def prior_events(ticker: str, since: datetime, until: datetime) -> int:
        assert ticker == "CSCO"
        return 12

    result = run_onboard(
        repo_root=tmp_path,
        ticker="CSCO",
        fiscal_period="FY2026-Q4",
        report_at=report,
        now=report - timedelta(days=10),
        dry_run=True,
        skip_pull=True,
        skip_ids=True,
        skip_fiscal=True,
        skip_quant=True,
        skip_llm=True,
        skip_panel=True,
        event_lister=prior_events,
    )
    assert result.mode == "onboard"
    assert result.prior_event_count == 12
    assert result.status == "completed"
    assert result.status != "first_print_fallback"


def test_run_onboard_first_print_when_lister_returns_zero(tmp_path: Path):
    report = datetime(2026, 9, 1, tzinfo=UTC)

    result = run_onboard(
        repo_root=tmp_path,
        ticker="ZZZZ",
        fiscal_period="FY2026-Q2",
        report_at=report,
        now=report - timedelta(days=10),
        dry_run=True,
        skip_pull=True,
        skip_ids=True,
        skip_fiscal=True,
        skip_quant=True,
        skip_llm=True,
        skip_panel=True,
        event_lister=lambda *_args: 0,
    )
    assert result.status == "first_print_fallback"
    assert result.mode == "first_print"
    assert result.prior_event_count == 0
    assert result.error and "FIRST-PRINT" in result.error


def test_run_onboard_fails_clearly_when_history_unavailable(tmp_path: Path):
    report = datetime(2026, 9, 1, tzinfo=UTC)

    def boom(ticker: str, since: datetime, until: datetime) -> int:
        raise ProviderHistoryUnavailable("QUARTR_API_KEY is not set; cannot count")

    result = run_onboard(
        repo_root=tmp_path,
        ticker="CSCO",
        fiscal_period="FY2026-Q4",
        report_at=report,
        now=report - timedelta(days=10),
        dry_run=True,
        skip_pull=True,
        skip_ids=True,
        skip_fiscal=True,
        skip_quant=True,
        skip_llm=True,
        skip_panel=True,
        event_lister=boom,
    )
    assert result.status == "failed"
    assert result.mode == "unknown"
    assert result.error and "QUARTR_API_KEY" in result.error


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


def test_pull_history_uses_mcp_seeded_disk_for_3y_lookback(tmp_path: Path):
    raw = tmp_path / "Structured Narrative" / "transcripts_raw"
    raw.mkdir(parents=True)
    (raw / "STRW_FY2025-Q1.txt").write_text("mcp body\n", encoding="utf-8")
    report = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    seen: list[list[str]] = []

    def fake_run(argv, *, cwd, dry_run, env=None):
        seen.append(list(argv))
        return {"argv": list(argv), "cwd": str(cwd), "dry_run": dry_run, "returncode": 0}

    steps = _pull_history_transcripts(
        repo_root=tmp_path,
        ticker="STRW",
        report_at=report,
        lookback_years=3,
        dry_run=False,
        run_command=fake_run,
    )
    assert steps[0]["step"] == "quartr_mcp_seed"
    assert steps[0]["lookback_years"] == 3
    assert "FY2025-Q1" in steps[0]["on_disk"]
    assert not any("quartr_history_import.py" in str(s.get("argv", [])) for s in steps)
    assert steps[0]["step"] == "quartr_mcp_seed"
    assert seen == []


def test_pull_history_hard_fails_when_mcp_disk_empty_without_roic_opt_in(tmp_path: Path):
    sn = tmp_path / "Structured Narrative"
    (sn / "transcripts_raw").mkdir(parents=True)
    report = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    seen: list[list[str]] = []

    def fake_run(argv, *, cwd, dry_run, env=None):
        seen.append(list(argv))
        return {"argv": list(argv), "cwd": str(cwd), "dry_run": dry_run, "returncode": 0}

    with pytest.raises(OnboardError, match="Seed via Quartr MCP"):
        _pull_history_transcripts(
            repo_root=tmp_path,
            ticker="STRW",
            report_at=report,
            lookback_years=3,
            dry_run=False,
            run_command=fake_run,
            allow_roic_fallback=False,
        )
    assert seen == []


def test_pull_history_roic_opt_in_when_mcp_disk_empty(tmp_path: Path):
    sn = tmp_path / "Structured Narrative"
    (sn / "transcripts_raw").mkdir(parents=True)
    fetch = (
        tmp_path
        / "earnings-scraper-main"
        / "earnings-scraper-main"
        / "scripts"
        / "fetch_transcripts.py"
    )
    fetch.parent.mkdir(parents=True)
    fetch.write_text("# stub\n", encoding="utf-8")
    report = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    calls: list[str] = []

    def fake_run(argv, *, cwd, dry_run, env=None):
        joined = " ".join(argv)
        calls.append(joined)
        if "fetch_transcripts.py" in joined:
            (sn / "transcripts_raw" / "STRW_FY2025-Q1.txt").write_text(
                "body\n", encoding="utf-8"
            )
        return {"argv": list(argv), "cwd": str(cwd), "dry_run": dry_run, "returncode": 0}

    steps = _pull_history_transcripts(
        repo_root=tmp_path,
        ticker="STRW",
        report_at=report,
        lookback_years=3,
        dry_run=False,
        run_command=fake_run,
        allow_roic_fallback=True,
    )
    assert steps[0]["step"] == "quartr_mcp_seed"
    assert steps[0]["on_disk"] == []
    assert any(s.get("step") == "roic_fetch_transcripts" for s in steps)
    assert any(s.get("step") == "export_inbox_to_transcripts_raw" for s in steps)
    assert any("fetch_transcripts.py" in c for c in calls)
    assert not any("quartr_history_import.py" in c for c in calls)


def test_pull_history_dry_run_does_not_call_quartr_rest(tmp_path: Path):
    (tmp_path / "Structured Narrative" / "transcripts_raw").mkdir(parents=True)
    report = datetime(2026, 8, 7, 16, 0, tzinfo=UTC)
    seen: list[list[str]] = []

    def fake_run(argv, *, cwd, dry_run, env=None):
        seen.append(list(argv))
        return {"argv": list(argv), "cwd": str(cwd), "dry_run": dry_run, "returncode": 0}

    steps = _pull_history_transcripts(
        repo_root=tmp_path,
        ticker="STRW",
        report_at=report,
        lookback_years=3,
        dry_run=True,
        run_command=fake_run,
    )
    assert steps[0]["step"] == "quartr_mcp_seed"
    assert steps[1]["step"] == "roic_fallback"
    assert steps[1]["allow_roic_fallback"] is False
    assert seen == []


def test_run_onboard_classifies_from_on_disk_mcp_without_quartr_rest(tmp_path: Path):
    raw = tmp_path / "Structured Narrative" / "transcripts_raw"
    raw.mkdir(parents=True)
    (raw / "STRW_FY2025-Q1.txt").write_text("mcp\n", encoding="utf-8")
    (raw / "STRW_FY2025-Q2.txt").write_text("mcp\n", encoding="utf-8")
    report = datetime(2026, 9, 1, tzinfo=UTC)

    result = run_onboard(
        repo_root=tmp_path,
        ticker="STRW",
        fiscal_period="FY2026-Q2",
        report_at=report,
        now=report - timedelta(days=10),
        dry_run=True,
        skip_pull=True,
        skip_ids=True,
        skip_fiscal=True,
        skip_quant=True,
        skip_llm=True,
        skip_panel=True,
        force_mode="onboard",
    )
    assert result.mode == "onboard"
    assert result.prior_event_count == 2
    count_step = next(s for s in result.steps if s.get("step") == "count_prior_events")
    assert count_step["source"] == "on_disk_mcp"
    assert result.status == "completed"


def test_sync_book_after_onboard_imports_and_marks_dirty(tmp_path: Path, monkeypatch):
    sector = tmp_path / "config" / "sectors" / "xlk_tech.txt"
    sector.parent.mkdir(parents=True)
    sector.write_text("AAPL\nMSFT\n", encoding="utf-8")
    db_path = tmp_path / "monitor.sqlite3"
    dataset = tmp_path / "company_quarters.parquet"
    monkeypatch.setenv("EARNINGS_MONITOR_DB", str(db_path))
    monkeypatch.setenv("EARNINGS_MONITOR_DATASET", str(dataset))

    calls: list[dict] = []

    class FakeHist:
        records = 12
        tickers = ("AAPL", "MSFT", "CSCO")
        missing_tickers = ()

    def fake_import(source_root, destination, *, tickers=()):
        calls.append(
            {
                "source_root": str(source_root),
                "destination": str(destination),
                "tickers": tuple(tickers),
            }
        )
        return FakeHist()

    steps = sync_book_after_onboard(
        repo_root=tmp_path,
        ticker="CSCO",
        fiscal_period="FY2026-Q4",
        configured_tickers=("AAPL", "MSFT"),
        import_history_fn=fake_import,
    )
    by_step = {step["step"]: step for step in steps}
    assert "book_sync" in by_step
    assert by_step["book_sync"].get("meta_updated") is True
    assert "CSCO" in by_step["book_sync"]["tickers"]
    assert "history_import" in by_step
    assert by_step["history_import"].get("error") is None
    assert "CSCO" in by_step["history_import"]["tickers"]
    assert "AAPL" in by_step["history_import"]["tickers"]  # full book, not wipe
    assert by_step["research_dirty"]["reason"] == "onboard"
    assert any("CSCO:FY2026-Q4" in str(t) for t in by_step["research_dirty"]["triggers"])
    assert calls and "CSCO" in calls[0]["tickers"]
    assert "CSCO" in sector.read_text(encoding="utf-8")


def test_run_onboard_panel_triggers_book_sync(tmp_path: Path, monkeypatch):
    report = datetime(2026, 9, 1, tzinfo=UTC)
    sector = tmp_path / "config" / "sectors" / "xlk_tech.txt"
    sector.parent.mkdir(parents=True)
    sector.write_text("AAPL\n", encoding="utf-8")
    (tmp_path / "Structured Narrative").mkdir(parents=True)
    monkeypatch.setenv("EARNINGS_MONITOR_DB", str(tmp_path / "monitor.sqlite3"))
    monkeypatch.setenv(
        "EARNINGS_MONITOR_DATASET", str(tmp_path / "company_quarters.parquet")
    )

    class FakeHist:
        records = 3
        tickers = ("AAPL", "CSCO")
        missing_tickers = ()

    def fake_run(argv, *, cwd, dry_run, env=None):
        return {"argv": list(argv), "cwd": str(cwd), "dry_run": dry_run, "returncode": 0}

    result = run_onboard(
        repo_root=tmp_path,
        ticker="CSCO",
        fiscal_period="FY2026-Q4",
        report_at=report,
        now=report - timedelta(days=10),
        dry_run=False,
        skip_pull=True,
        skip_ids=True,
        skip_fiscal=True,
        skip_quant=True,
        skip_llm=True,
        skip_panel=False,
        force_mode="onboard",
        prior_event_count=5,
        configured_tickers=("AAPL",),
        run_command=fake_run,
        import_history_fn=lambda *a, **k: FakeHist(),
    )
    assert result.status == "completed"
    steps = {s.get("step") for s in result.steps}
    assert "build_feature_panel" in steps
    assert "history_import" in steps
    assert "research_dirty" in steps
    assert "refreshed" in result.history_import_note.lower() or "dirty" in (
        result.history_import_note.lower()
    )
