from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest

from services.earnings_monitor.config import MonitorConfig
from services.earnings_monitor.dashboard.data import DashboardData
from services.earnings_monitor.models import EarningsEvent, MonitoredEvent
from services.earnings_monitor.state import OperationalState
from services.earnings_monitor.storage import (
    ArtifactStore,
    CompletedEventArtifactPublisher,
    ImmutableArtifactError,
    LocalArtifactStore,
    S3ArtifactStore,
    StorageError,
)


def _event(now: datetime) -> EarningsEvent:
    return EarningsEvent(
        provider_event_id="quartr:event/42",
        ticker="MU",
        fiscal_period="FY2026-Q4",
        report_at=now,
        call_at=now + timedelta(hours=1),
    )


def test_r2_config_derives_endpoint_and_rejects_partial_credentials(tmp_path: Path) -> None:
    config = MonitorConfig.from_env(
        {
            "EARNINGS_MONITOR_R2_ACCOUNT_ID": "account-123",
            "EARNINGS_MONITOR_R2_BUCKET": "roz-artifacts",
            "EARNINGS_MONITOR_R2_PREFIX": "/prod/roz/",
            "EARNINGS_MONITOR_R2_ACCESS_KEY_ID": "access",
            "EARNINGS_MONITOR_R2_SECRET_ACCESS_KEY": "secret",
        },
        repo_root=tmp_path,
    )
    assert config.r2_enabled
    assert config.r2_endpoint_url == (
        "https://account-123.r2.cloudflarestorage.com"
    )
    assert config.r2_prefix == "prod/roz"

    partial = MonitorConfig.from_env(
        {"EARNINGS_MONITOR_R2_BUCKET": "roz-artifacts"}, repo_root=tmp_path
    )
    with pytest.raises(ValueError, match="requires endpoint/account"):
        _ = partial.r2_enabled


class _FakeR2Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], tuple[bytes, dict[str, str]]] = {}

    def put_object(self, *, Bucket, Key, Body, Metadata, IfNoneMatch):
        assert IfNoneMatch == "*"
        location = (Bucket, Key)
        if location in self.objects:
            raise RuntimeError("precondition failed")
        self.objects[location] = (bytes(Body), dict(Metadata))

    def get_object(self, *, Bucket, Key):
        return {"Body": BytesIO(self.objects[(Bucket, Key)][0])}

    def head_object(self, *, Bucket, Key):
        body, metadata = self.objects[(Bucket, Key)]
        return {"ContentLength": len(body), "Metadata": metadata}


def test_r2_s3_boundary_is_prefixed_immutable_and_idempotent() -> None:
    client = _FakeR2Client()
    store = S3ArtifactStore("roz-artifacts", prefix="production/roz", client=client)

    first = store.put_bytes("events/MU/complete.json", b"complete")
    repeated = store.put_bytes("events/MU/complete.json", b"complete")

    assert first.sha256 == repeated.sha256
    assert (
        "roz-artifacts",
        "production/roz/events/MU/complete.json",
    ) in client.objects
    with pytest.raises(ImmutableArtifactError, match="different bytes"):
        store.put_bytes("events/MU/complete.json", b"changed")


class _FailManifestOnce(ArtifactStore):
    def __init__(self, delegate: LocalArtifactStore) -> None:
        self.delegate = delegate
        self.failed = False

    def put_bytes(self, key, data, *, metadata=None):
        if key.endswith("complete.json") and not self.failed:
            self.failed = True
            raise StorageError("simulated final marker failure")
        return self.delegate.put_bytes(key, data, metadata=metadata)

    def get_bytes(self, key):
        return self.delegate.get_bytes(key)

    def exists(self, key):
        return self.delegate.exists(key)

    def list(self, prefix=""):
        return self.delegate.list(prefix)


def test_completed_event_publication_is_retry_safe_and_manifest_last(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 24, 20, tzinfo=UTC)
    transcript = tmp_path / "Structured Narrative" / "transcripts_raw" / "MU_FY2026-Q4.txt"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(b"final transcript\n")
    registry = (
        tmp_path
        / "Structured Narrative"
        / "output"
        / "MU"
        / "json"
        / "quarter_registry.json"
    )
    registry.parent.mkdir(parents=True)
    registry.write_bytes(b'{"quarter":"FY2026-Q4"}')
    event_report = registry.parent / "FY2026-Q4-scorecard.json"
    event_report.write_bytes(b'{"event":"quartr-event-42"}')
    unrelated = registry.parent / "FY2026-Q3-scorecard.json"
    unrelated.write_bytes(b'{"event":"older-event"}')
    store = _FailManifestOnce(LocalArtifactStore(tmp_path / "r2-fake"))
    publisher = CompletedEventArtifactPublisher(store, tmp_path)
    kwargs = {
        "event": _event(now),
        "fingerprint": "abc123",
        "workflow_result": {
            "profile": "post_call",
            "transcript_path": str(transcript),
            "artifact_paths": [str(event_report)],
        },
        "completed_at": "2026-09-24T23:00:00+00:00",
    }

    with pytest.raises(StorageError, match="final marker"):
        publisher.publish(**kwargs)
    assert not store.exists(
        "events/MU/FY2026-Q4/quartr-event-42/abc123/complete.json"
    )

    publication = publisher.publish(**kwargs)
    assert publication.manifest.key.endswith("/complete.json")
    assert len(publication.artifacts) == 3
    assert store.get_bytes(publication.artifacts[0].key) == b"final transcript\n"
    keys = [ref.key for ref in publication.artifacts]
    assert any(key.endswith("FY2026-Q4-scorecard.json") for key in keys)
    assert not any(key.endswith("quarter_registry.json") for key in keys)
    assert not any(key.endswith("FY2026-Q3-scorecard.json") for key in keys)


def test_operational_audit_history_and_publication_retry(tmp_path: Path) -> None:
    now = datetime(2026, 9, 24, 20, tzinfo=UTC)
    state = OperationalState(tmp_path / "monitor.sqlite3")
    state.initialize()
    event = _event(now)
    state.upsert_event(MonitoredEvent(event))
    assert state.enqueue(
        idempotency_key="event:stage:v1",
        provider_event_id=event.provider_event_id,
        payload={"stage": "post_call"},
        max_attempts=2,
        available_at=now,
    )
    job = state.claim_next_job(now)
    assert job is not None
    run_id = state.start_job_run(job, stage="post_call", started_at=now)
    state.finish_job_run(
        run_id,
        result={"commands": ["score"]},
        finished_at=now + timedelta(seconds=3),
    )
    runs = state.list_job_runs(provider_event_id=event.provider_event_id)
    assert runs[0]["duration_ms"] == 3000
    assert runs[0]["status"] == "succeeded"

    cycle_id = state.start_poll_cycle(now)
    state.finish_poll_cycle(
        cycle_id,
        result={"discovered": 1, "queued": 1, "jobs": 1},
        finished_at=now + timedelta(seconds=5),
    )
    assert state.list_poll_cycles()[0]["duration_ms"] == 5000

    state.enqueue_artifact_publication(
        publication_key="event:abc",
        provider_event_id=event.provider_event_id,
        fingerprint="abc",
        payload={"workflow_result": {}, "completed_at": now.isoformat()},
        max_attempts=2,
        available_at=now,
    )
    publication = state.claim_artifact_publication(now)
    assert publication is not None
    state.finish_artifact_publication(
        publication["id"],
        success=False,
        error="temporary",
        retry_delay=timedelta(seconds=10),
        finished_at=now,
    )
    assert state.claim_artifact_publication(now + timedelta(seconds=9)) is None
    assert state.claim_artifact_publication(now + timedelta(seconds=10)) is not None


def test_initialize_recovers_only_stale_artifact_publication_leases(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 9, 24, 20, tzinfo=UTC)
    state = OperationalState(
        tmp_path / "monitor.sqlite3",
        lease_timeout=timedelta(minutes=5),
    )
    state.initialize(now=now)
    event = _event(now)
    state.upsert_event(MonitoredEvent(event))
    state.enqueue_artifact_publication(
        publication_key="event:lease",
        provider_event_id=event.provider_event_id,
        fingerprint="lease",
        payload={"workflow_result": {}, "completed_at": now.isoformat()},
        max_attempts=2,
        available_at=now,
    )
    claimed = state.claim_artifact_publication(now)
    assert claimed is not None

    state.initialize(now=now + timedelta(minutes=4))
    assert state.list_artifact_publications()[0]["status"] == "running"
    assert state.claim_artifact_publication(now + timedelta(minutes=4)) is None

    state.initialize(now=now + timedelta(minutes=5))
    recovered = state.list_artifact_publications()[0]
    assert recovered["status"] == "pending"
    assert recovered["attempts"] == 1
    retried = state.claim_artifact_publication(now + timedelta(minutes=5))
    assert retried is not None and retried["attempts"] == 2


def test_dashboard_classifies_stuck_and_repeated_failures(tmp_path) -> None:
    # Point the host feed at a path that does not exist: this asserts pure
    # classification of the records below. Without it the real repo's
    # host_quartr/health/last_run.json leaks in and adds host_feed_stale
    # as soon as anyone has actually run the host automation.
    absent_host_health = tmp_path / "no-host-health.json"
    now = datetime(2026, 9, 24, 23, tzinfo=UTC)
    data = DashboardData.from_records(
        [],
        operational_events=[
            {
                "provider_event_id": "event-1",
                "ticker": "MU",
                "state": "quant_running",
                "updated_at": (now - timedelta(hours=3)).isoformat(),
            }
        ],
        job_runs=[
            {
                "provider_event_id": "event-1",
                "status": "failed",
                "started_at": (now - timedelta(minutes=10)).isoformat(),
            },
            {
                "provider_event_id": "event-1",
                "status": "failed",
                "started_at": (now - timedelta(minutes=20)).isoformat(),
            },
        ],
        poll_cycles=[
            {
                "started_at": (now - timedelta(hours=1)).isoformat(),
                "finished_at": (now - timedelta(hours=1)).isoformat(),
            }
        ],
    )

    alerts = data.operational_alerts(
        now=now,
        stuck_after_seconds=7200,
        repeated_failure_threshold=2,
        host_health_path=absent_host_health,
    )
    assert {alert["kind"] for alert in alerts} == {
        "stuck_event",
        "repeated_failure",
        "stale_poller",
    }
    repeated = next(alert for alert in alerts if alert["kind"] == "repeated_failure")
    assert repeated["occurrence"] == (now - timedelta(minutes=20)).isoformat()
    assert data.event_inbox(now=now)[0]["stuck"] is True
