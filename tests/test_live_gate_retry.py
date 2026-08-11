from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from services.earnings_monitor.config import MonitorConfig
from services.earnings_monitor.freshness import AlwaysFreshProbe
from services.earnings_monitor.models import (
    EarningsEvent,
    EventState,
    MonitoredEvent,
    TranscriptDocument,
    TranscriptStatus,
)
from services.earnings_monitor.service import EarningsMonitor
from services.earnings_monitor.state import OperationalState
from services.earnings_monitor.transcripts import transcript_fingerprint

UTC = timezone.utc


def _config(tmp_path: Path) -> MonitorConfig:
    (tmp_path / "Structured Narrative").mkdir(exist_ok=True)
    return MonitorConfig(
        repo_root=tmp_path,
        database_path=tmp_path / "state.sqlite3",
        inbox_path=tmp_path / "inbox",
        stabilization_seconds=0,
        minimum_transcript_chars=10,
        require_live_growth=False,
        max_job_attempts=1,
        research_regen_after_post_call=False,
    )


def test_live_fingerprint_set_only_after_success(tmp_path: Path):
    now = datetime(2026, 8, 10, 15, tzinfo=UTC)
    event = EarningsEvent(
        "event-live-ok",
        "AAPL",
        "FY2026-Q3",
        report_at=now - timedelta(hours=2),
        call_at=now - timedelta(hours=1),
    )
    transcript = TranscriptDocument(
        "AAPL",
        "FY2026-Q3",
        "live transcript long enough for scoring path here",
        "quartr",
        "doc-live-ok",
        status=TranscriptStatus.LIVE,
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
        event,
        state=EventState.POST_CALL_QUEUED,
        transcript_fingerprint=fingerprint,
        transcript_observed_at=now - timedelta(minutes=10),
    )
    state.upsert_event(monitored)
    state.enqueue(
        idempotency_key="post:live-ok",
        provider_event_id="event-live-ok",
        payload={
            "stage": "post_call",
            "fingerprint": fingerprint,
            "transcript_status": "live",
        },
        max_attempts=1,
        available_at=now,
    )
    service = EarningsMonitor(
        config=_config(tmp_path),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=AlwaysFreshProbe(),
        workflow=Workflow(),
        clock=lambda: now,
    )
    assert service.run_next_job()
    done = state.get_event("event-live-ok")
    assert done.state == EventState.COMPLETE
    assert done.live_post_call_fingerprint == fingerprint


def test_exhausted_live_failure_clears_gate_for_retry(tmp_path: Path):
    now = datetime(2026, 8, 10, 15, tzinfo=UTC)
    event = EarningsEvent(
        "event-live-fail",
        "AAPL",
        "FY2026-Q3",
        report_at=now - timedelta(hours=2),
        call_at=now - timedelta(hours=1),
    )
    transcript = TranscriptDocument(
        "AAPL",
        "FY2026-Q3",
        "live transcript long enough for scoring path here",
        "quartr",
        "doc-live-fail",
        status=TranscriptStatus.LIVE,
    )
    fingerprint = transcript_fingerprint(transcript.content)

    class Provider:
        def list_events(self, tickers, *, since, until):
            return []

        def get_transcript(self, requested):
            return transcript

    class Workflow:
        def run(self, profile, requested, transcript=None, **kwargs):
            raise RuntimeError("model timeout")

    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    monitored = MonitoredEvent(
        event,
        state=EventState.POST_CALL_QUEUED,
        transcript_fingerprint=fingerprint,
        transcript_observed_at=now - timedelta(minutes=10),
        live_post_call_fingerprint="stale-from-old-build",
    )
    state.upsert_event(monitored)
    state.enqueue(
        idempotency_key="post:live-fail",
        provider_event_id="event-live-fail",
        payload={
            "stage": "post_call",
            "fingerprint": fingerprint,
            "transcript_status": "live",
        },
        max_attempts=1,
        available_at=now,
    )
    service = EarningsMonitor(
        config=_config(tmp_path),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=AlwaysFreshProbe(),
        workflow=Workflow(),
        clock=lambda: now,
    )
    assert service.run_next_job()
    after = state.get_event("event-live-fail")
    assert after.live_post_call_fingerprint is None
    assert after.state == EventState.TRANSCRIPT_PENDING
