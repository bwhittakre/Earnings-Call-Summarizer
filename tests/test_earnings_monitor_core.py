from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.earnings_monitor.config import MonitorConfig, PILOT_TICKERS
from services.earnings_monitor.freshness import AlwaysFreshProbe, SnowflakeFreshnessProbe
from services.earnings_monitor.models import (
    EarningsEvent,
    EventState,
    InvalidTransition,
    MonitoredEvent,
    TranscriptDocument,
)
from services.earnings_monitor.notifications import TwoEmailNotifier
from services.earnings_monitor.providers import LocalInboxProvider, QuartrAdapter
from services.earnings_monitor.service import EarningsMonitor
from services.earnings_monitor.state import OperationalState
from services.earnings_monitor.transcripts import TranscriptStabilizer, transcript_fingerprint
from services.earnings_monitor.workflow import LazyStructuredNarrativeWorkflow

UTC = timezone.utc


def config(tmp_path: Path, **overrides) -> MonitorConfig:
    values = {
        "repo_root": tmp_path,
        "database_path": tmp_path / "state.sqlite3",
        "inbox_path": tmp_path / "inbox",
        "stabilization_seconds": 0,
        "minimum_transcript_chars": 10,
    }
    values.update(overrides)
    return MonitorConfig(**values)


def event(now: datetime) -> EarningsEvent:
    return EarningsEvent(
        "event-1",
        "amzn",
        "FY2026-Q2",
        report_at=now - timedelta(minutes=2),
        call_at=now - timedelta(minutes=1),
    )


def test_config_restricts_universe_and_parses_environment(tmp_path):
    parsed = MonitorConfig.from_env(
        {
            "EARNINGS_MONITOR_TICKERS": "amzn,MSFT,amzn",
            "EARNINGS_MONITOR_STABILIZATION_SECONDS": "0",
        },
        repo_root=tmp_path,
    )
    assert parsed.tickers == ("AMZN", "MSFT")
    assert parsed.stabilization_seconds == 0
    with pytest.raises(ValueError):
        MonitorConfig.from_env({"EARNINGS_MONITOR_TICKERS": "TSLA"}, repo_root=tmp_path)
    assert PILOT_TICKERS == ("AMZN", "MSFT", "NVDA", "AAPL")


def test_state_machine_rejects_skipped_transitions():
    monitored = MonitoredEvent(event(datetime.now(UTC)))
    with pytest.raises(InvalidTransition):
        monitored.transition(EventState.QUANT_RUNNING)
    monitored.transition(EventState.BASELINE_QUEUED)
    monitored.transition(EventState.BASELINE_RUNNING)
    monitored.transition(EventState.AWAITING_RELEASE)
    monitored.transition(EventState.AWAITING_QUANT_DATA)
    monitored.transition(EventState.QUANT_QUEUED)
    monitored.transition(EventState.QUANT_RUNNING)
    monitored.transition(EventState.AWAITING_CALL)
    monitored.transition(EventState.TRANSCRIPT_PENDING)
    monitored.transition(EventState.TRANSCRIPT_UNSTABLE)
    monitored.transition(EventState.POST_CALL_QUEUED)
    monitored.transition(EventState.POST_CALL_RUNNING)
    monitored.transition(EventState.COMPLETE)


def test_sqlite_queue_is_idempotent_and_retries_atomically(tmp_path):
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    monitored = MonitoredEvent(event(datetime.now(UTC)))
    state.upsert_event(monitored)
    assert state.enqueue(
        idempotency_key="same", provider_event_id="event-1", payload={"x": 1}, max_attempts=2
    )
    assert not state.enqueue(
        idempotency_key="same", provider_event_id="event-1", payload={"x": 1}, max_attempts=2
    )
    first = state.claim_next_job()
    assert first and first["attempts"] == 1 and first["payload"] == {"x": 1}
    assert state.claim_next_job() is None
    state.finish_job(first["id"], success=False, error="temporary")
    second = state.claim_next_job()
    assert second and second["id"] == first["id"] and second["attempts"] == 2
    state.finish_job(second["id"], success=False, error="permanent")
    assert state.claim_next_job() is None


def test_stabilizer_resets_window_when_content_changes():
    now = datetime.now(UTC)
    stabilizer = TranscriptStabilizer(stable_for=timedelta(seconds=60), minimum_chars=5)
    document = TranscriptDocument("AMZN", "FY2026-Q2", "hello world", "fake", "doc")
    first = stabilizer.assess(
        document, previous_fingerprint=None, first_observed_at=None, now=now
    )
    assert not first.ready
    stable = stabilizer.assess(
        document,
        previous_fingerprint=first.fingerprint,
        first_observed_at=first.first_observed_at,
        now=now + timedelta(seconds=60),
    )
    assert stable.ready
    changed = TranscriptDocument("AMZN", "FY2026-Q2", "hello changed", "fake", "doc")
    reset = stabilizer.assess(
        changed,
        previous_fingerprint=first.fingerprint,
        first_observed_at=first.first_observed_at,
        now=now + timedelta(seconds=61),
    )
    assert not reset.ready and reset.first_observed_at == now + timedelta(seconds=61)
    assert transcript_fingerprint("a  b\r\n") == transcript_fingerprint("a b")


def test_local_provider_and_quartr_adapter_are_injected_and_offline(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    path = inbox / "amzn-fy2026-q2.txt"
    path.write_text("# company: AMZN\n# period: FY2026 Q2\n\nPrepared remarks\nQ&A", encoding="utf-8")
    provider = LocalInboxProvider(inbox)
    now = datetime.now(UTC)
    events = provider.list_events(["AMZN"], since=now - timedelta(minutes=1), until=now + timedelta(minutes=1))
    assert len(events) == 1
    assert provider.get_transcript(events[0]).content == "Prepared remarks\nQ&A"

    class Gateway:
        def search_events(self, **kwargs):
            return [
                {
                    "id": "q1",
                    "company": {"ticker": "MSFT"},
                    "fiscalYear": 2026,
                    "eventType": "q_4",
                    "title": "Q4 2026",
                    "date": now.isoformat(),
                    "contentDates": [
                        {
                            "contentType": "audio",
                            "date": now.isoformat(),
                            "contentStatus": "confirmed",
                        },
                        {
                            "contentType": "report",
                            "date": (now - timedelta(hours=1)).isoformat(),
                            "contentStatus": "confirmedDateEstimatedTime",
                        },
                    ],
                }
            ]

        def fetch_transcript(self, **kwargs):
            return {
                "transcript": {
                    "id": "d1",
                    "text": "transcript",
                    "updatedAt": now,
                }
            }

    adapter = QuartrAdapter(Gateway())
    quartr_event = adapter.list_events(["MSFT"], since=now, until=now)[0]
    assert quartr_event.fiscal_period == "FY2026-Q4"
    assert quartr_event.report_at < quartr_event.call_at
    assert adapter.get_transcript(quartr_event).source_id == "d1"


def test_three_stage_ordering_freshness_gate_and_email_timing(tmp_path):
    start = datetime.now(UTC)
    current = [start]
    earnings_event = EarningsEvent(
        "event-1",
        "AMZN",
        "FY2026-Q2",
        report_at=start + timedelta(minutes=10),
        call_at=start + timedelta(minutes=30),
    )
    document = [TranscriptDocument("AMZN", "FY2026-Q2", "long enough transcript", "fake", "doc")]

    class Provider:
        def list_events(self, tickers, *, since, until):
            return [earnings_event]

        def get_transcript(self, requested):
            return document[0]

    class Freshness:
        checks = 0
        fresh = False

        def check(self, ticker, fiscal_period):
            self.checks += 1
            from services.earnings_monitor.freshness import FreshnessResult

            return FreshnessResult(ticker, fiscal_period, self.fresh, detail="expected quarter")

    class Workflow:
        calls = []

        def run(self, profile, requested, transcript=None):
            self.calls.append((profile, transcript.content if transcript else None))
            return {"profile": profile}

    class Notifier:
        calls = []

        def pre_call_quant(self, requested, *, detail=""):
            self.calls.append(("pre_call", current[0]))
            return True

        def final_combined(self, requested, *, success, detail=""):
            self.calls.append(("final", current[0]))
            return True

    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    workflow, freshness, notifier = Workflow(), Freshness(), Notifier()
    service = EarningsMonitor(
        config=config(tmp_path),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=freshness,
        workflow=workflow,
        notifier=notifier,
        clock=lambda: current[0],
    )
    assert service.discover(since=start - timedelta(days=1), until=start + timedelta(days=1)) == 1

    assert service.advance_events() == 1
    assert service.run_next_job()
    assert workflow.calls == [("pre_release", None)]
    assert freshness.checks == 0
    assert service.advance_events() == 0  # still before the release

    current[0] = start + timedelta(minutes=11)
    assert service.advance_events() == 0  # enters expected-quarter polling
    assert service.advance_events() == 0
    assert freshness.checks == 1 and workflow.calls == [("pre_release", None)]
    freshness.fresh = True
    assert service.advance_events() == 1
    assert service.run_next_job()
    assert workflow.calls[-1] == ("release_to_call", None)
    assert notifier.calls == [("pre_call", current[0])]
    assert current[0] < earnings_event.call_at

    current[0] = start + timedelta(minutes=31)
    assert service.advance_events() == 0  # enters transcript polling
    assert service.advance_events() == 0  # first fingerprint observation
    assert service.advance_events() == 1  # same version is now stable
    assert service.run_next_job()
    assert [call[0] for call in workflow.calls] == [
        "pre_release",
        "release_to_call",
        "post_call",
    ]
    assert notifier.calls[-1][0] == "final"
    assert state.get_event("event-1").state == EventState.COMPLETE

    # Same content is deduplicated; a revision resets stabilization and gets a
    # new fingerprinted post-call job only after a confirming observation.
    assert service.advance_events() == 0
    document[0] = TranscriptDocument(
        "AMZN", "FY2026-Q2", "long enough transcript revised", "fake", "doc-2"
    )
    assert service.advance_events() == 0
    assert service.advance_events() == 1
    assert service.run_next_job()
    assert [call[0] for call in workflow.calls].count("post_call") == 2


def test_two_email_notifier_is_idempotent(tmp_path):
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()

    class Sender:
        messages = []

        def send(self, message):
            self.messages.append(message)

    sender = Sender()
    notifier = TwoEmailNotifier(
        state=state, sender=sender, sender_address="monitor@example.com", recipients=("ops@example.com",)
    )
    earnings_event = event(datetime.now(UTC))
    assert notifier.pre_call_quant(earnings_event)
    assert not notifier.pre_call_quant(earnings_event)
    assert notifier.final_combined(earnings_event, success=True)
    assert not notifier.final_combined(earnings_event, success=True)
    assert len(sender.messages) == 2


def test_freshness_and_real_workflow_profile_adapter(tmp_path):
    captured = {}

    def query(sql, params):
        captured.update(params)
        return {"is_fresh": True, "as_of": "2026-07-29T12:00:00Z"}

    result = SnowflakeFreshnessProbe(query).check("aapl", "FY2026-Q3")
    assert result.is_fresh and result.as_of.tzinfo is not None
    assert captured["ticker"] == "AAPL"

    repo_root = Path(__file__).resolve().parents[1]
    commands = []
    workflow = LazyStructuredNarrativeWorkflow(repo_root, runner=commands.append)
    earnings_event = event(datetime.now(UTC))
    transcript = TranscriptDocument("AMZN", "FY2026-Q2", "text", "fake", "doc")
    assert workflow.available()[0]
    result = workflow.run("pre_release", earnings_event)
    assert result["profile"] == "pre_release"
    assert commands and "--baseline-quarter" in commands[0].argv

    # Post-call transcript persistence uses the exact path consumed by the
    # existing LocalFileProvider, without importing Structured Narrative.
    local_adapter = LazyStructuredNarrativeWorkflow(tmp_path)
    path = local_adapter.persist_transcript(earnings_event, transcript)
    assert path == (
        tmp_path
        / "Structured Narrative"
        / "transcripts_raw"
        / "AMZN_FY2026-Q2.txt"
    )
    assert path.read_text(encoding="utf-8") == "text\n"
