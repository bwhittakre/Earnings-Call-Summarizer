from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.earnings_monitor.cli import main as monitor_main
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


def seed_prior_transcript(
    repo_root: Path, ticker: str, prior_period: str, *, text: str = "prior transcript"
) -> Path:
    """Create a local prior transcript so pre_release is not auto-skipped."""
    path = (
        repo_root
        / "Structured Narrative"
        / "transcripts_raw"
        / f"{ticker.upper()}_{prior_period.upper()}.txt"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")
    return path


def seed_overlay(repo_root: Path, ticker: str) -> Path:
    """Create a minimal company overlay so discover eligibility passes."""
    path = (
        repo_root
        / "Structured Narrative"
        / "config"
        / "company_overlays"
        / f"{ticker.upper()}.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        path.write_text("{}", encoding="utf-8")
    return path


def test_config_parses_configurable_universe_and_environment(tmp_path):
    parsed = MonitorConfig.from_env(
        {
            "EARNINGS_MONITOR_TICKERS": "amzn,MSFT,amzn",
            "EARNINGS_MONITOR_STABILIZATION_SECONDS": "0",
        },
        repo_root=tmp_path,
    )
    assert parsed.tickers == ("AMZN", "MSFT")
    assert parsed.stabilization_seconds == 0
    assert parsed.lease_timeout_seconds == 3600
    expanded = MonitorConfig.from_env(
        {"EARNINGS_MONITOR_TICKERS": "TSLA,MU"}, repo_root=tmp_path
    )
    assert expanded.tickers == ("TSLA", "MU")
    with pytest.raises(ValueError):
        MonitorConfig.from_env({"EARNINGS_MONITOR_TICKERS": "$$$"}, repo_root=tmp_path)
    assert PILOT_TICKERS == ("MSFT", "AAPL", "NVDA", "MU")


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
    assert state.claim_next_job() is None
    second = state.claim_next_job(datetime.now(UTC) + timedelta(seconds=61))
    assert second and second["id"] == first["id"] and second["attempts"] == 2
    state.finish_job(second["id"], success=False, error="permanent")
    assert state.claim_next_job() is None


def test_stale_job_lease_recovery_reconciles_job_run_and_event(tmp_path):
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    state = OperationalState(
        tmp_path / "monitor.sqlite3",
        lease_timeout=timedelta(minutes=5),
    )
    state.initialize(now=now)
    monitored = MonitoredEvent(
        event(now),
        state=EventState.POST_CALL_RUNNING,
    )
    state.upsert_event(monitored)
    assert state.enqueue(
        idempotency_key="post-call",
        provider_event_id="event-1",
        payload={"stage": "post_call", "fingerprint": "abc"},
        max_attempts=2,
        available_at=now,
    )
    job = state.claim_next_job(now)
    assert job is not None
    state.start_job_run(job, stage="post_call", started_at=now)

    state.initialize(now=now + timedelta(minutes=4))
    assert state.list_job_runs()[0]["status"] == "running"
    assert state.get_event("event-1").state == EventState.POST_CALL_RUNNING
    assert state.claim_next_job(now + timedelta(minutes=4)) is None

    state.initialize(now=now + timedelta(minutes=5))
    run = state.list_job_runs()[0]
    assert run["status"] == "failed"
    assert run["finished_at"] == (now + timedelta(minutes=5)).isoformat()
    recovered = state.get_event("event-1")
    assert recovered.state == EventState.POST_CALL_QUEUED
    assert recovered.last_error == "worker lease expired before completion"
    retried = state.claim_next_job(now + timedelta(minutes=5))
    assert retried is not None and retried["attempts"] == 2


def test_manual_arm_updates_existing_period_without_replacing_identity_or_lifecycle(
    tmp_path,
    monkeypatch,
):
    database = tmp_path / "monitor.sqlite3"
    now = datetime(2026, 7, 31, 12, tzinfo=UTC)
    state = OperationalState(database)
    state.initialize()
    state.upsert_event(
        MonitoredEvent(
            EarningsEvent(
                "watched-provider-id",
                "AMZN",
                "FY2026-Q2",
                report_at=now,
                call_at=now + timedelta(hours=1),
            ),
            state=EventState.AWAITING_CALL,
        )
    )
    monkeypatch.setenv("EARNINGS_MONITOR_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EARNINGS_MONITOR_DB", str(database))
    monkeypatch.setenv("EARNINGS_MONITOR_TICKERS", "AMZN")
    seed_overlay(tmp_path, "AMZN")

    assert monitor_main(
        [
            "arm",
            "--ticker",
            "AMZN",
            "--period",
            "FY2026-Q2",
            "--report-at",
            (now + timedelta(minutes=10)).isoformat(),
            "--call-at",
            (now + timedelta(hours=2)).isoformat(),
            "--title",
            "Operator correction",
        ]
    ) == 0

    armed = state.get_event("watched-provider-id")
    assert armed is not None
    assert armed.state == EventState.AWAITING_CALL
    assert armed.manual_override is True
    assert armed.event.title == "Operator correction"
    assert armed.event.call_at == now + timedelta(hours=2)
    assert state.get_event("manual:AMZN:FY2026-Q2") is None


@pytest.mark.parametrize(
    "persisted_state",
    [
        EventState.TRANSCRIPT_PENDING,
        EventState.TRANSCRIPT_UNSTABLE,
        EventState.FAILED,
    ],
)
def test_state_initialization_preserves_current_lifecycle_states(
    tmp_path,
    persisted_state,
):
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    state.upsert_event(
        MonitoredEvent(
            event(datetime.now(UTC)),
            state=persisted_state,
            last_error="retained" if persisted_state == EventState.FAILED else None,
        )
    )

    state.initialize()

    restored = state.get_event("event-1")
    assert restored.state == persisted_state
    assert restored.last_error == (
        "retained" if persisted_state == EventState.FAILED else None
    )


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
    manually_armed = EarningsEvent(
        "manual:AMZN:FY2026-Q2",
        "AMZN",
        "FY2026-Q2",
        report_at=now - timedelta(hours=1),
        call_at=now,
    )
    assert provider.get_transcript(manually_armed).source_id == str(path.resolve())

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
    seed_prior_transcript(tmp_path, "AMZN", "FY2026-Q1")
    seed_overlay(tmp_path, "AMZN")

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

        def run(self, profile, requested, transcript=None, *, no_prior=False):
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
        config=config(tmp_path, tickers=("AMZN",)),
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

    freshness.fresh = False
    current[0] = start + timedelta(minutes=76)
    assert service.advance_events() == 0
    waiting = state.get_event("event-1")
    assert waiting.state == EventState.AWAITING_QUANT_DATA
    assert waiting.transcript_fingerprint is not None

    freshness.fresh = True
    assert service.advance_events() == 1
    assert service.run_next_job()
    assert workflow.calls[-1] == ("release_to_call", None)
    assert notifier.calls == [("pre_call", current[0])]
    assert service.advance_events() == 0  # enters transcript polling
    assert service.advance_events() == 1  # previously observed version is stable
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


def test_transcript_timeout_fails_final_stage_and_notifies(tmp_path):
    start = datetime.now(UTC)
    earnings_event = event(start)

    class Provider:
        def list_events(self, tickers, *, since, until):
            return []

        def get_transcript(self, requested):
            return None

    class Workflow:
        def run(self, profile, requested, transcript=None, *, no_prior=False):
            return {}

    class Notifier:
        calls = []

        def pre_call_quant(self, requested, *, detail=""):
            return True

        def final_combined(self, requested, *, success, detail=""):
            self.calls.append((success, detail))
            return True

    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    monitored = MonitoredEvent(earnings_event, state=EventState.AWAITING_CALL)
    state.upsert_event(monitored)
    notifier = Notifier()
    service = EarningsMonitor(
        config=config(
            tmp_path,
            transcript_start_delay_seconds=0,
            transcript_timeout_seconds=60,
        ),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=AlwaysFreshProbe(),
        workflow=Workflow(),
        notifier=notifier,
        clock=lambda: earnings_event.call_at + timedelta(seconds=61),
    )

    assert service.advance_events() == 0
    failed = state.get_event(earnings_event.provider_event_id)
    assert failed.state == EventState.FAILED
    assert notifier.calls and notifier.calls[0][0] is False


def test_transcript_timeout_recovers_when_document_arrives_after_restart(tmp_path):
    start = datetime.now(UTC)
    earnings_event = event(start)
    transcript = TranscriptDocument(
        "AMZN",
        "FY2026-Q2",
        "completed transcript long enough",
        "quartr",
        "doc-1",
    )

    class Provider:
        def list_events(self, tickers, *, since, until):
            return []

        def get_transcript(self, requested):
            return transcript

    class Workflow:
        calls = []

        def run(self, profile, requested, transcript=None, *, no_prior=False):
            self.calls.append((profile, transcript.source_id))
            return {}

    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    monitored = MonitoredEvent(
        earnings_event,
        state=EventState.FAILED,
        last_error="transcript unavailable before 60-second timeout",
    )
    state.upsert_event(monitored)
    workflow = Workflow()
    service = EarningsMonitor(
        config=config(
            tmp_path,
            transcript_start_delay_seconds=0,
            transcript_timeout_seconds=60,
        ),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=AlwaysFreshProbe(),
        workflow=workflow,
        clock=lambda: earnings_event.call_at + timedelta(hours=1),
    )

    assert service.advance_events() == 0
    assert state.get_event(earnings_event.provider_event_id).state == EventState.TRANSCRIPT_PENDING
    assert service.advance_events() == 0
    assert state.get_event(earnings_event.provider_event_id).state == EventState.TRANSCRIPT_UNSTABLE
    assert service.advance_events() == 1
    assert service.run_next_job()
    assert state.get_event(earnings_event.provider_event_id).state == EventState.COMPLETE
    assert workflow.calls == [("post_call", "doc-1")]


def test_isolated_tomorrow_shadow_fixture_runs_complete_lifecycle(
    tmp_path,
    monkeypatch,
):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    database = tmp_path / "shadow.sqlite3"
    monkeypatch.setenv("EARNINGS_MONITOR_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EARNINGS_MONITOR_DB", str(database))
    monkeypatch.setenv("EARNINGS_MONITOR_INBOX", str(inbox))
    monkeypatch.setenv("EARNINGS_MONITOR_PROVIDER", "manual")
    monkeypatch.setenv("EARNINGS_MONITOR_TICKERS", "MU")

    report_at = datetime(2026, 7, 31, 13, 0, tzinfo=UTC)
    call_at = datetime(2026, 7, 31, 14, 0, tzinfo=UTC)
    seed_prior_transcript(tmp_path, "MU", "FY2026-Q2")
    seed_overlay(tmp_path, "MU")
    assert monitor_main(
        [
            "arm",
            "--ticker",
            "MU",
            "--period",
            "FY2026-Q3",
            "--event-id",
            "fixture:MU:FY2026-Q3",
            "--title",
            "Isolated Roz shadow fixture",
            "--report-at",
            report_at.isoformat(),
            "--call-at",
            call_at.isoformat(),
        ]
    ) == 0

    state = OperationalState(database)
    armed = state.get_event("fixture:MU:FY2026-Q3")
    assert armed and armed.state == EventState.SCHEDULED
    assert armed.first_print is False

    current = [report_at - timedelta(hours=2)]
    transcript = TranscriptDocument(
        "MU",
        "FY2026-Q3",
        "fixture transcript long enough",
        "fixture",
        "fixture-doc",
    )

    class Provider:
        def list_events(self, tickers, *, since, until):
            return []

        def get_transcript(self, requested):
            return transcript

    class Workflow:
        calls = []

        def run(self, profile, requested, transcript=None, *, no_prior=False):
            self.calls.append(profile)
            return {"profile": profile}

    class Notifier:
        calls = []

        def pre_call_quant(self, requested, *, detail=""):
            self.calls.append(("quant", True))
            return True

        def final_combined(self, requested, *, success, detail=""):
            self.calls.append(("final", success))
            return True

    workflow, notifier = Workflow(), Notifier()
    service = EarningsMonitor(
        config=config(
            tmp_path,
            tickers=("MU",),
            transcript_start_delay_seconds=45 * 60,
            transcript_timeout_seconds=3 * 60 * 60,
        ),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=AlwaysFreshProbe(),
        workflow=workflow,
        notifier=notifier,
        clock=lambda: current[0],
    )

    assert service.advance_events() == 1
    assert service.run_next_job()
    current[0] = report_at
    assert service.advance_events() == 0
    assert service.advance_events() == 1
    assert service.run_next_job()

    current[0] = call_at + timedelta(minutes=44)
    assert service.advance_events() == 0
    assert state.get_event("fixture:MU:FY2026-Q3").state == EventState.AWAITING_CALL

    current[0] = call_at + timedelta(minutes=46)
    assert service.advance_events() == 0
    assert sum(service.advance_events() for _ in range(2)) == 1
    assert service.run_next_job()
    assert state.get_event("fixture:MU:FY2026-Q3").state == EventState.COMPLETE
    assert workflow.calls == ["pre_release", "release_to_call", "post_call"]
    assert notifier.calls == [("quant", True), ("final", True)]
    assert service.advance_events() == 0


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
    assert notifier.final_combined(earnings_event, success=False)
    assert not notifier.final_combined(earnings_event, success=False)
    assert notifier.final_combined(earnings_event, success=True)
    assert not notifier.final_combined(earnings_event, success=True)
    assert len(sender.messages) == 3


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

    first_print_commands = []
    first_print_workflow = LazyStructuredNarrativeWorkflow(
        repo_root, runner=first_print_commands.append
    )
    empty = first_print_workflow.run("pre_release", earnings_event, no_prior=True)
    assert empty["profile"] == "pre_release"
    assert empty["commands"] == []
    assert first_print_commands == []

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


def test_first_print_arm_skips_pre_release(tmp_path, monkeypatch, capsys):
    database = tmp_path / "monitor.sqlite3"
    monkeypatch.setenv("EARNINGS_MONITOR_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EARNINGS_MONITOR_DB", str(database))
    monkeypatch.setenv("EARNINGS_MONITOR_TICKERS", "SPCX")
    report_at = datetime(2026, 8, 4, 20, 0, tzinfo=UTC)
    call_at = datetime(2026, 8, 4, 21, 0, tzinfo=UTC)
    assert (
        monitor_main(
            [
                "arm",
                "--ticker",
                "SPCX",
                "--period",
                "FY2026-Q2",
                "--event-id",
                "quartr:692542",
                "--report-at",
                report_at.isoformat(),
                "--call-at",
                call_at.isoformat(),
                "--first-print",
            ]
        )
        == 0
    )
    payload = __import__("json").loads(capsys.readouterr().out)
    assert payload["first_print"] is True
    assert payload["state"] == "scheduled"

    class Provider:
        def list_events(self, tickers, *, since, until):
            return []

        def get_transcript(self, requested):
            return None

    class Workflow:
        calls = []

        def run(self, profile, requested, transcript=None, *, no_prior=False):
            self.calls.append((profile, no_prior))
            return {"profile": profile}

    state = OperationalState(database)
    workflow = Workflow()
    service = EarningsMonitor(
        config=config(tmp_path, tickers=("SPCX",)),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=AlwaysFreshProbe(),
        workflow=workflow,
        clock=lambda: report_at - timedelta(hours=1),
    )
    assert service.advance_events() == 0
    monitored = state.get_event("quartr:692542")
    assert monitored is not None
    assert monitored.state == EventState.AWAITING_RELEASE
    assert monitored.first_print is True
    assert workflow.calls == []
    assert state.claim_next_job() is None


def test_auto_skip_pre_release_when_prior_transcript_missing(tmp_path):
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    seed_overlay(tmp_path, "SPCX")
    earnings_event = EarningsEvent(
        "event-spcx",
        "SPCX",
        "FY2026-Q2",
        report_at=now + timedelta(hours=4),
        call_at=now + timedelta(hours=5),
    )

    class Provider:
        def list_events(self, tickers, *, since, until):
            return [earnings_event]

        def get_transcript(self, requested):
            return None

    class Workflow:
        calls = []

        def run(self, profile, requested, transcript=None, *, no_prior=False):
            self.calls.append(profile)
            return {}

    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    service = EarningsMonitor(
        config=config(tmp_path, tickers=("SPCX",)),
        state=state,
        event_provider=Provider(),
        transcript_provider=Provider(),
        freshness=AlwaysFreshProbe(),
        workflow=Workflow(),
        clock=lambda: now,
    )
    assert service.discover(since=now, until=now + timedelta(days=1)) == 1
    assert service.advance_events() == 0
    monitored = state.get_event("event-spcx")
    assert monitored.state == EventState.AWAITING_RELEASE
    assert monitored.first_print is True
    assert state.claim_next_job() is None


def test_arm_first_print_unfails_failed_baseline(tmp_path, monkeypatch, capsys):
    database = tmp_path / "monitor.sqlite3"
    state = OperationalState(database)
    state.initialize()
    now = datetime(2026, 8, 4, 12, tzinfo=UTC)
    state.upsert_event(
        MonitoredEvent(
            EarningsEvent(
                "quartr:692542",
                "SPCX",
                "FY2026-Q2",
                report_at=now,
                call_at=now + timedelta(hours=1),
            ),
            state=EventState.FAILED,
            last_error="prior transcript missing",
        )
    )
    monkeypatch.setenv("EARNINGS_MONITOR_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("EARNINGS_MONITOR_DB", str(database))
    monkeypatch.setenv("EARNINGS_MONITOR_TICKERS", "SPCX")
    assert (
        monitor_main(
            [
                "arm",
                "--ticker",
                "SPCX",
                "--period",
                "FY2026-Q2",
                "--event-id",
                "quartr:692542",
                "--report-at",
                now.isoformat(),
                "--call-at",
                (now + timedelta(hours=1)).isoformat(),
                "--first-print",
            ]
        )
        == 0
    )
    armed = state.get_event("quartr:692542")
    assert armed is not None
    assert armed.state == EventState.SCHEDULED
    assert armed.first_print is True
    assert armed.last_error is None
