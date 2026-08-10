"""Tests for the async Rank IC / consolidated research regen loop."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.earnings_monitor.cli import main as monitor_main
from services.earnings_monitor.config import MonitorConfig
from services.earnings_monitor.freshness import AlwaysFreshProbe
from services.earnings_monitor.models import (
    EarningsEvent,
    EventState,
    MonitoredEvent,
    TranscriptDocument,
)
from services.earnings_monitor.research_regen import (
    RegenCommandResult,
    RegenRunResult,
    build_consolidated_command,
    build_rank_ic_command,
    run_research_regen_once,
)
from services.earnings_monitor.service import EarningsMonitor
from services.earnings_monitor.state import OperationalState
from services.earnings_monitor.transcripts import transcript_fingerprint

UTC = timezone.utc


def _config(tmp_path: Path, **overrides) -> MonitorConfig:
    values = {
        "repo_root": tmp_path,
        "database_path": tmp_path / "state.sqlite3",
        "inbox_path": tmp_path / "inbox",
        "stabilization_seconds": 0,
        "minimum_transcript_chars": 10,
        "research_regen_after_post_call": True,
        "research_regen_debounce_seconds": 60,
        "tickers": ("AAPL", "MSFT"),
        "research_sector": "xlk_tech",
        "research_min_calendar_quarter": "2016-Q2",
    }
    values.update(overrides)
    return MonitorConfig(**values)


def test_config_parses_research_regen_knobs(tmp_path):
    parsed = MonitorConfig.from_env(
        {
            "EARNINGS_MONITOR_RESEARCH_REGEN": "false",
            "EARNINGS_MONITOR_RESEARCH_REGEN_DEBOUNCE_SECONDS": "15",
            "EARNINGS_MONITOR_RESEARCH_REGEN_IDLE_SECONDS": "5",
            "EARNINGS_MONITOR_RESEARCH_MIN_CALENDAR_QUARTER": "2018-Q1",
            "EARNINGS_MONITOR_RESEARCH_SECTOR": "mega_cap_tech",
        },
        repo_root=tmp_path,
    )
    assert parsed.research_regen_after_post_call is False
    assert parsed.research_regen_debounce_seconds == 15
    assert parsed.research_regen_idle_seconds == 5
    assert parsed.research_min_calendar_quarter == "2018-Q1"
    assert parsed.research_sector == "mega_cap_tech"


def test_research_book_dirty_coalesces_triggers(tmp_path):
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    first = state.mark_research_book_dirty(
        reason="post_call",
        trigger="AAPL:FY2026-Q3",
        now=datetime(2026, 8, 3, 12, 0, tzinfo=UTC),
    )
    second = state.mark_research_book_dirty(
        reason="post_call",
        trigger="MSFT:FY2026-Q4",
        now=datetime(2026, 8, 3, 12, 5, tzinfo=UTC),
    )
    dirty = state.research_book_dirty()
    assert dirty is not None
    assert dirty["dirty"] is True
    assert dirty["marked_at"] == first["marked_at"]
    assert dirty["triggers"] == ["AAPL:FY2026-Q3", "MSFT:FY2026-Q4"]
    assert second["updated_at"] != first["marked_at"]
    state.clear_research_book_dirty()
    assert state.research_book_dirty() is None


def test_post_call_marks_research_book_dirty_when_enabled(tmp_path):
    now = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
    earnings_event = EarningsEvent(
        "event-dirty",
        "AAPL",
        "FY2026-Q3",
        report_at=now - timedelta(hours=2),
        call_at=now - timedelta(hours=1),
    )
    transcript = TranscriptDocument(
        "AAPL",
        "FY2026-Q3",
        "completed transcript long enough for post-call",
        "quartr",
        "doc-1",
    )
    fingerprint = transcript_fingerprint(transcript.content)

    class Provider:
        def list_events(self, tickers, *, since, until):
            return []

        def get_transcript(self, requested):
            return transcript

    class Workflow:
        def run(self, profile, requested, transcript=None, **kwargs):
            return {"ok": True}

    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    monitored = MonitoredEvent(
        earnings_event,
        state=EventState.POST_CALL_QUEUED,
        transcript_fingerprint=fingerprint,
        transcript_observed_at=now - timedelta(minutes=10),
    )
    state.upsert_event(monitored)
    state.enqueue(
        idempotency_key="post:event-dirty",
        provider_event_id="event-dirty",
        payload={"stage": "post_call", "fingerprint": fingerprint},
        max_attempts=1,
        available_at=now,
    )
    service = EarningsMonitor(
        config=_config(tmp_path, research_regen_after_post_call=True),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=AlwaysFreshProbe(),
        workflow=Workflow(),
        clock=lambda: now,
    )
    assert service.run_next_job()
    assert state.get_event("event-dirty").state == EventState.COMPLETE
    dirty = state.research_book_dirty()
    assert dirty is not None
    assert dirty["triggers"] == ["AAPL:FY2026-Q3"]


def test_post_call_skips_dirty_mark_when_regen_disabled(tmp_path):
    now = datetime(2026, 8, 3, 15, 0, tzinfo=UTC)
    earnings_event = EarningsEvent(
        "event-clean",
        "AAPL",
        "FY2026-Q3",
        report_at=now - timedelta(hours=2),
        call_at=now - timedelta(hours=1),
    )
    transcript = TranscriptDocument(
        "AAPL",
        "FY2026-Q3",
        "completed transcript long enough for post-call",
        "quartr",
        "doc-1",
    )
    fingerprint = transcript_fingerprint(transcript.content)

    class Provider:
        def list_events(self, tickers, *, since, until):
            return []

        def get_transcript(self, requested):
            return transcript

    class Workflow:
        def run(self, profile, requested, transcript=None, **kwargs):
            return {}

    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    monitored = MonitoredEvent(
        earnings_event,
        state=EventState.POST_CALL_QUEUED,
        transcript_fingerprint=fingerprint,
        transcript_observed_at=now - timedelta(minutes=10),
    )
    state.upsert_event(monitored)
    state.enqueue(
        idempotency_key="post:event-clean",
        provider_event_id="event-clean",
        payload={"stage": "post_call", "fingerprint": fingerprint},
        max_attempts=1,
        available_at=now,
    )
    service = EarningsMonitor(
        config=_config(tmp_path, research_regen_after_post_call=False),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=AlwaysFreshProbe(),
        workflow=Workflow(),
        clock=lambda: now,
    )
    assert service.run_next_job()
    assert state.research_book_dirty() is None


def test_regen_once_skips_when_not_dirty(tmp_path):
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    result = run_research_regen_once(_config(tmp_path), state, force=False)
    assert result.skipped
    assert result.skip_reason == "not_dirty"
    assert result.ok


def test_regen_once_honors_debounce(tmp_path):
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    state.mark_research_book_dirty(
        trigger="AAPL:FY2026-Q3",
        now=datetime.now(UTC),
    )
    result = run_research_regen_once(
        _config(tmp_path, research_regen_debounce_seconds=3600),
        state,
        force=False,
        honor_debounce=True,
    )
    assert result.skipped
    assert result.skip_reason == "debounce_3600s"
    assert state.research_book_dirty() is not None


def test_regen_once_clears_dirty_before_run_and_redirties_on_failure(tmp_path):
    sn = tmp_path / "Structured Narrative"
    sn.mkdir()
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    state.mark_research_book_dirty(
        trigger="AAPL:FY2026-Q3",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    def failing_runner(config, *, triggered_by="manual", python=None):
        assert state.research_book_dirty() is None  # cleared before run
        return RegenRunResult(
            triggered_by=triggered_by,
            started_at="t0",
            finished_at="t1",
            commands=(
                RegenCommandResult(
                    name="evaluate_narrative_signals",
                    command=("python", "evaluate"),
                    returncode=1,
                    duration_seconds=0.1,
                ),
            ),
        )

    result = run_research_regen_once(
        _config(tmp_path, research_regen_debounce_seconds=0),
        state,
        force=False,
        honor_debounce=False,
        runner=failing_runner,
    )
    assert not result.ok
    dirty = state.research_book_dirty()
    assert dirty is not None
    assert dirty["reason"] == "regen_failed"


def test_regen_once_redirties_when_runner_raises(tmp_path):
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    state.mark_research_book_dirty(
        trigger="AAPL:FY2026-Q3",
        now=datetime(2026, 1, 1, tzinfo=UTC),
    )

    def exploding_runner(config, *, triggered_by="manual", python=None):
        raise FileNotFoundError("Structured Narrative directory missing")

    try:
        run_research_regen_once(
            _config(tmp_path, research_regen_debounce_seconds=0),
            state,
            force=False,
            honor_debounce=False,
            runner=exploding_runner,
        )
        assert False, "expected FileNotFoundError"
    except FileNotFoundError:
        pass
    dirty = state.research_book_dirty()
    assert dirty is not None
    assert dirty["reason"] == "regen_exception"


def test_regen_once_force_runs_even_when_clean(tmp_path):
    sn = tmp_path / "Structured Narrative"
    sn.mkdir()
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    calls = []

    def ok_runner(config, *, triggered_by="manual", python=None):
        calls.append(triggered_by)
        return RegenRunResult(
            triggered_by=triggered_by,
            started_at="t0",
            finished_at="t1",
            commands=(
                RegenCommandResult(
                    name="evaluate_narrative_signals",
                    command=("python", "evaluate"),
                    returncode=0,
                    duration_seconds=0.1,
                ),
                RegenCommandResult(
                    name="build_consolidated_panel_report",
                    command=("python", "build"),
                    returncode=0,
                    duration_seconds=0.1,
                ),
            ),
        )

    result = run_research_regen_once(
        _config(tmp_path),
        state,
        force=True,
        runner=ok_runner,
    )
    assert result.ok
    assert not result.skipped
    assert calls == ["force"]
    assert state.research_book_dirty() is None


def test_regen_command_builders_use_book_defaults(tmp_path):
    cfg = _config(tmp_path)
    rank = build_rank_ic_command(cfg, python="python")
    rank_full = build_rank_ic_command(cfg, python="python", fast_regen=False)
    consol = build_consolidated_command(cfg, python="python")
    assert "--min-calendar-quarter" in rank
    assert "2016-Q2" in rank
    assert "AAPL" in rank and "MSFT" in rank
    assert "--no-jackknife" in rank
    assert "--no-jackknife" not in rank_full
    assert "--sector" in consol
    assert "xlk_tech" in consol
    assert "2016-Q2" in consol


def test_research_regen_cli_once_not_dirty(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("EARNINGS_MONITOR_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EARNINGS_MONITOR_DB", str(tmp_path / "monitor.sqlite3"))
    monkeypatch.setenv("EARNINGS_MONITOR_INBOX", str(tmp_path / "inbox"))
    (tmp_path / "inbox").mkdir()
    code = monitor_main(["research-regen"])
    captured = capsys.readouterr().out
    assert code == 0
    assert '"skipped": true' in captured
    assert '"skip_reason": "not_dirty"' in captured
