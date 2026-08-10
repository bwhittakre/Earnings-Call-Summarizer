from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.earnings_monitor.cli import build_local_monitor
from services.earnings_monitor.config import MonitorConfig
from services.earnings_monitor.freshness import AlwaysFreshProbe
from services.earnings_monitor.models import (
    EarningsEvent,
    EventState,
    MonitoredEvent,
    TranscriptStatus,
)
from services.earnings_monitor.providers import (
    LocalInboxProvider,
    WatchedEventManifestProvider,
    write_transcript_bundle_atomic,
)
from services.earnings_monitor.service import EarningsMonitor
from services.earnings_monitor.state import OperationalState

UTC = timezone.utc


def _event_manifest(*, call_at: datetime, report_at: datetime | None = None) -> dict:
    return {
        "schema_version": 1,
        "provider_event_id": "quartr:event-1",
        "ticker": "AAPL",
        "fiscal_period": "FY2026-Q3",
        "report_at": (report_at or call_at - timedelta(hours=1)).isoformat(),
        "call_at": call_at.isoformat(),
        "title": "Apple FY2026 Q3 earnings call",
        "source_url": "https://example.test/events/1",
    }


def _bundle(
    *,
    status: str,
    observed_at: datetime,
    document_id: str,
    text: str = "Revenue grew and guidance was raised for next quarter.",
) -> dict:
    return {
        "schema_version": 1,
        "provider_event_id": "quartr:event-1",
        "provider_document_id": document_id,
        "ticker": "AAPL",
        "fiscal_period": "FY2026-Q3",
        "source_url": f"https://example.test/documents/{document_id}",
        "status": status,
        "observed_at": observed_at.isoformat(),
        "speaker_text": [
            {"speaker": "  Tim   Cook ", "text": f"  {text}  "},
            {"speaker": "Analyst", "text": "What changed in the outlook?"},
        ],
    }


def _seed_overlay(tmp_path: Path, ticker: str = "AAPL") -> Path:
    path = (
        tmp_path
        / "Structured Narrative"
        / "config"
        / "company_overlays"
        / f"{ticker.upper()}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text("{}", encoding="utf-8")
    return path


def _config(tmp_path: Path) -> MonitorConfig:
    _seed_overlay(tmp_path, "AAPL")
    return MonitorConfig(
        repo_root=tmp_path,
        database_path=tmp_path / "monitor.sqlite3",
        inbox_path=tmp_path / "inbox",
        event_manifest_path=tmp_path / "events",
        tickers=("AAPL",),
        provider="watched",
        stabilization_seconds=0,
        minimum_transcript_chars=10,
        transcript_start_delay_seconds=0,
        transcript_timeout_seconds=3600,
    )


def test_watched_provider_config_and_cli_wiring(tmp_path):
    manifest_dir = tmp_path / "assisted-events"
    parsed = MonitorConfig.from_env(
        {
            "EARNINGS_MONITOR_PROVIDER": "watched",
            "EARNINGS_MONITOR_EVENT_MANIFESTS": str(manifest_dir),
            "EARNINGS_MONITOR_INBOX": str(tmp_path / "inbox"),
            "EARNINGS_MONITOR_TICKERS": "AAPL",
        },
        repo_root=tmp_path,
    )
    monitor = build_local_monitor(parsed)
    assert parsed.event_manifest_path == manifest_dir
    assert isinstance(monitor.event_provider, WatchedEventManifestProvider)
    assert isinstance(monitor.transcript_provider, LocalInboxProvider)


def test_watched_manifests_deduplicate_correct_and_reject_malformed(tmp_path, caplog):
    watched = tmp_path / "events"
    watched.mkdir()
    initial = datetime(2026, 7, 30, 21, 0, tzinfo=UTC)
    corrected = initial + timedelta(minutes=30)
    (watched / "01.event.json").write_text(
        json.dumps(_event_manifest(call_at=initial)), encoding="utf-8"
    )
    (watched / "bad.event.json").write_text('{"schema_version": 1,', encoding="utf-8")
    duplicate = watched / "02.event.json"
    duplicate.write_text(
        json.dumps(_event_manifest(call_at=corrected)), encoding="utf-8"
    )
    future = datetime.now().timestamp() + 5
    os.utime(duplicate, (future, future))

    provider = WatchedEventManifestProvider(watched)
    events = provider.list_events(
        ["AAPL"],
        since=initial - timedelta(days=1),
        until=corrected + timedelta(days=1),
    )

    assert len(events) == 1
    assert events[0].call_at == corrected
    assert "Ignoring malformed event manifest" in caplog.text


def test_discovery_updates_times_idempotently_but_preserves_manual_override(tmp_path):
    now = datetime(2026, 7, 30, 21, 0, tzinfo=UTC)
    current = [now]
    event = EarningsEvent(
        "quartr:event-1",
        "AAPL",
        "FY2026-Q3",
        report_at=now - timedelta(hours=1),
        call_at=now,
        title="Apple call",
        source_url="https://example.test/events/1",
    )

    class Provider:
        def list_events(self, tickers, *, since, until):
            return [event]

        def get_transcript(self, requested):
            return None

    class Workflow:
        def run(self, profile, requested, transcript=None):
            return {}

    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    monitor = EarningsMonitor(
        config=_config(tmp_path),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=AlwaysFreshProbe(),
        workflow=Workflow(),
        clock=lambda: current[0],
    )
    assert monitor.discover(since=now - timedelta(days=1), until=now + timedelta(days=1)) == 1
    assert monitor.discover(since=now - timedelta(days=1), until=now + timedelta(days=1)) == 0

    event = EarningsEvent(
        "quartr:event-1",
        "AAPL",
        "FY2026-Q3",
        report_at=now - timedelta(hours=2),
        call_at=now + timedelta(minutes=15),
        title="Corrected Apple call",
        source_url="https://example.test/events/1",
    )
    assert monitor.discover(since=now - timedelta(days=1), until=now + timedelta(days=1)) == 1
    assert state.get_event(event.provider_event_id).event.call_at == event.call_at

    overridden = state.get_event(event.provider_event_id)
    overridden.manual_override = True
    overridden.event = EarningsEvent(
        event.provider_event_id,
        event.ticker,
        event.fiscal_period,
        report_at=now - timedelta(hours=3),
        call_at=now + timedelta(hours=1),
        title="Operator override",
        source_url=event.source_url,
    )
    state.upsert_event(overridden)
    assert monitor.discover(since=now - timedelta(days=1), until=now + timedelta(days=1)) == 0
    assert state.get_event(event.provider_event_id).event.title == "Operator override"

    # A watched provider ID that differs from the default manual ID for the
    # same quarter must not violate the SQLite uniqueness constraint or replace
    # the operator's schedule.
    event = EarningsEvent(
        "quartr:event-2",
        "AAPL",
        "FY2026-Q3",
        report_at=now - timedelta(hours=1),
        call_at=now,
    )
    assert monitor.discover(since=now - timedelta(days=1), until=now + timedelta(days=1)) == 0
    assert state.get_event_for_period("AAPL", "FY2026-Q3").event.title == "Operator override"


def test_bundle_live_to_final_naming_compatibility_and_malformed_safety(tmp_path, caplog):
    inbox = tmp_path / "inbox"
    now = datetime(2026, 7, 30, 22, 0, tzinfo=UTC)
    write_transcript_bundle_atomic(
        inbox / "AAPL_FY2026_Q3.transcript.json",
        _bundle(status="live", observed_at=now, document_id="live-1"),
    )
    (inbox / "broken-FY2026-Q3.transcript.json").write_text(
        json.dumps({"schema_version": 1}), encoding="utf-8"
    )
    provider = LocalInboxProvider(inbox)
    event = EarningsEvent(
        "quartr:event-1",
        "AAPL",
        "FY2026-Q3",
        report_at=now - timedelta(hours=2),
        call_at=now - timedelta(hours=1),
    )

    live = provider.get_transcript(event)
    assert live.status == TranscriptStatus.LIVE
    assert live.content.startswith("Tim Cook: Revenue grew")
    assert "Ignoring malformed transcript bundle" in caplog.text

    write_transcript_bundle_atomic(
        inbox / "AAPL-FY2026-Q3.transcript.json",
        _bundle(
            status="final",
            observed_at=now + timedelta(minutes=10),
            document_id="final-1",
        ),
    )
    final = provider.get_transcript(event)
    assert final.status == TranscriptStatus.FINAL
    assert final.source_id == "final-1"

    legacy = inbox / "MSFT_FY2026_Q4.txt"
    legacy.write_text("# company: MSFT\n# period: FY2026 Q4\n\nLegacy body", encoding="utf-8")
    legacy_event = EarningsEvent(
        "manual:MSFT:FY2026-Q4",
        "MSFT",
        "FY2026-Q4",
        report_at=now,
        call_at=now,
    )
    assert provider.get_transcript(legacy_event).content == "Legacy body"


def test_final_bundle_restart_recovery_and_duplicate_delivery(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    now = datetime(2026, 7, 30, 23, 0, tzinfo=UTC)
    event = EarningsEvent(
        "quartr:event-1",
        "AAPL",
        "FY2026-Q3",
        report_at=now - timedelta(hours=2),
        call_at=now - timedelta(hours=1),
    )
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    state.upsert_event(MonitoredEvent(event, state=EventState.AWAITING_CALL))

    class Workflow:
        calls: list[str] = []

        def run(self, profile, requested, transcript=None, *, no_prior=False):
            self.calls.append(transcript.source_id)
            return {}

    workflow = Workflow()

    def service() -> EarningsMonitor:
        return EarningsMonitor(
            config=_config(tmp_path),
            state=OperationalState(tmp_path / "monitor.sqlite3"),
            event_provider=WatchedEventManifestProvider(tmp_path / "events"),
            transcript_provider=LocalInboxProvider(inbox),
            freshness=AlwaysFreshProbe(),
            workflow=workflow,
            clock=lambda: now,
        )

    write_transcript_bundle_atomic(
        inbox / "AAPL-FY2026-Q3.transcript.json",
        _bundle(status="live", observed_at=now, document_id="live-1"),
    )
    first = service()
    first.state.initialize()
    assert first.advance_events() == 0
    assert first.advance_events() == 0
    assert first.state.get_event(event.provider_event_id).state == EventState.TRANSCRIPT_UNSTABLE

    write_transcript_bundle_atomic(
        inbox / "AAPL-FY2026-Q3.transcript.json",
        _bundle(
            status="final",
            observed_at=now,
            document_id="final-1",
            text="Final polished transcript after the call ended.",
        ),
    )
    restarted = service()
    restarted.state.initialize()
    # New final content: first poll observes, second stagnates and enqueues.
    assert restarted.advance_events() == 0
    assert restarted.advance_events() == 1
    assert restarted.run_next_job()
    assert workflow.calls == ["final-1"]
    assert restarted.state.get_event(event.provider_event_id).state == EventState.COMPLETE

    # Re-delivering the same final payload after another restart cannot enqueue
    # a second post-call job because both fingerprint and job key are durable.
    write_transcript_bundle_atomic(
        inbox / "AAPL_FY2026_Q3.transcript.json",
        _bundle(
            status="final",
            observed_at=now,
            document_id="final-duplicate",
            text="Final polished transcript after the call ended.",
        ),
    )
    final_restart = service()
    final_restart.state.initialize()
    assert final_restart.advance_events() == 0
    assert not final_restart.run_next_job()
    assert workflow.calls == ["final-1"]


def test_one_live_post_call_then_final_rescore(tmp_path):
    """LIVE scores at most once; FINAL with new fingerprint may re-score."""
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    now = datetime(2026, 7, 30, 23, 0, tzinfo=UTC)
    event = EarningsEvent(
        "quartr:event-live-1",
        "AAPL",
        "FY2026-Q3",
        report_at=now - timedelta(hours=2),
        call_at=now - timedelta(hours=1),
    )
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    state.upsert_event(MonitoredEvent(event, state=EventState.AWAITING_CALL))

    class Workflow:
        calls: list[str] = []

        def run(self, profile, requested, transcript=None, *, no_prior=False):
            self.calls.append(transcript.source_id)
            return {}

    workflow = Workflow()
    config = MonitorConfig(
        repo_root=tmp_path,
        database_path=tmp_path / "monitor.sqlite3",
        inbox_path=inbox,
        event_manifest_path=tmp_path / "events",
        tickers=("AAPL",),
        provider="watched",
        stabilization_seconds=0,
        minimum_transcript_chars=10,
        require_live_growth=False,
        transcript_start_delay_seconds=0,
        transcript_timeout_seconds=3600,
    )

    def service() -> EarningsMonitor:
        return EarningsMonitor(
            config=config,
            state=OperationalState(tmp_path / "monitor.sqlite3"),
            event_provider=WatchedEventManifestProvider(tmp_path / "events"),
            transcript_provider=LocalInboxProvider(inbox),
            freshness=AlwaysFreshProbe(),
            workflow=workflow,
            clock=lambda: now,
        )

    def live_bundle(document_id: str, text: str) -> dict:
        row = _bundle(status="live", observed_at=now, document_id=document_id, text=text)
        row["provider_event_id"] = event.provider_event_id
        return row

    def final_bundle(document_id: str, text: str) -> dict:
        row = _bundle(status="final", observed_at=now, document_id=document_id, text=text)
        row["provider_event_id"] = event.provider_event_id
        return row

    write_transcript_bundle_atomic(
        inbox / "AAPL-FY2026-Q3.transcript.json",
        live_bundle("live-1", "First live draft of the call."),
    )
    monitor = service()
    monitor.state.initialize()
    assert monitor.advance_events() == 0  # AWAITING_CALL → TRANSCRIPT_PENDING
    assert monitor.advance_events() == 0  # first observation: not ready
    assert monitor.advance_events() == 1  # stagnated LIVE → one post_call
    assert monitor.run_next_job()
    assert workflow.calls == ["live-1"]
    scored = monitor.state.get_event(event.provider_event_id)
    assert scored is not None
    assert scored.state == EventState.COMPLETE
    assert scored.live_post_call_fingerprint
    assert scored.live_scored_at is not None

    # Further LIVE growth must not enqueue another post_call.
    write_transcript_bundle_atomic(
        inbox / "AAPL-FY2026-Q3.transcript.json",
        live_bundle("live-2", "Second live draft with more Q&A content."),
    )
    monitor = service()
    monitor.state.initialize()
    assert monitor.advance_events() == 0
    assert monitor.advance_events() == 0
    assert not monitor.run_next_job()
    assert workflow.calls == ["live-1"]
    still = monitor.state.get_event(event.provider_event_id)
    assert still is not None
    assert still.state == EventState.COMPLETE
    assert still.live_post_call_fingerprint == scored.live_post_call_fingerprint

    # FINAL with a new fingerprint may re-score.
    write_transcript_bundle_atomic(
        inbox / "AAPL-FY2026-Q3.transcript.json",
        final_bundle("final-1", "Final polished transcript after the call."),
    )
    monitor = service()
    monitor.state.initialize()
    # COMPLETE → UNSTABLE on new fingerprint; next poll stagnates and enqueues.
    assert monitor.advance_events() == 0
    assert monitor.advance_events() == 1
    assert monitor.run_next_job()
    assert workflow.calls == ["live-1", "final-1"]
    assert monitor.state.get_event(event.provider_event_id).state == EventState.COMPLETE


def test_require_live_growth_wired_from_env(tmp_path):
    parsed = MonitorConfig.from_env(
        {
            "EARNINGS_MONITOR_PROVIDER": "manual",
            "EARNINGS_MONITOR_INBOX": str(tmp_path / "inbox"),
            "EARNINGS_MONITOR_TICKERS": "AAPL",
            "EARNINGS_MONITOR_REQUIRE_LIVE_GROWTH": "0",
        },
        repo_root=tmp_path,
    )
    assert parsed.require_live_growth is False
    monitor = build_local_monitor(parsed)
    assert monitor.stabilizer.require_live_growth is False
