"""Polling and idempotent job orchestration for the local monitor."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Protocol

from .config import MonitorConfig
from .freshness import FreshnessProbe
from .models import EventState, MonitoredEvent
from .providers import EventProvider, TranscriptProvider
from .state import OperationalState
from .transcripts import TranscriptStabilizer
from .workflow import Workflow

LOG = logging.getLogger(__name__)


class Notifier(Protocol):
    def pre_call_quant(self, event, *, detail: str = "") -> bool: ...
    def final_combined(self, event, *, success: bool, detail: str = "") -> bool: ...
    def stall_failure(
        self,
        event,
        *,
        stage: str,
        attempts: int | None,
        detail: str,
        recovery: str | None = None,
    ) -> bool: ...
    def operational_alert(self, alert: Mapping[str, Any]) -> bool: ...


class ArtifactPublisher(Protocol):
    def publish(
        self,
        *,
        event: Any,
        fingerprint: str,
        workflow_result: Mapping[str, Any],
        completed_at: str,
    ) -> Any: ...


class EarningsMonitor:
    def __init__(
        self,
        *,
        config: MonitorConfig,
        state: OperationalState,
        event_provider: EventProvider,
        transcript_provider: TranscriptProvider,
        freshness: FreshnessProbe,
        workflow: Workflow,
        notifier: Notifier | None = None,
        artifact_publisher: ArtifactPublisher | None = None,
        clock=None,
    ):
        self.config = config
        self.state = state
        self.event_provider = event_provider
        self.transcript_provider = transcript_provider
        self.freshness = freshness
        self.workflow = workflow
        self.notifier = notifier
        self.artifact_publisher = artifact_publisher
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.stabilizer = TranscriptStabilizer(
            stable_for=timedelta(seconds=config.stabilization_seconds),
            minimum_chars=config.minimum_transcript_chars,
        )

    def _refresh_history_dataset(self) -> dict | None:
        if not self.config.refresh_history_after_workflow:
            return None
        if self.config.history_source_path is None or self.config.dataset_path is None:
            raise RuntimeError(
                "History refresh requires EARNINGS_MONITOR_HISTORY_SOURCE "
                "and EARNINGS_MONITOR_DATASET"
            )
        from .history_import import import_history

        refresh = import_history(
            self.config.history_source_path,
            self.config.dataset_path,
            tickers=self.config.tickers,
        )
        return {
            "records": refresh.records,
            "quarters": refresh.quarters,
            "missing_tickers": list(refresh.missing_tickers),
        }

    def _notify_failure(
        self,
        event,
        *,
        stage: str,
        attempts: int | None,
        detail: str,
        recovery: str | None = None,
    ) -> None:
        if not self.notifier:
            return
        method = getattr(self.notifier, "stall_failure", None)
        if callable(method):
            method(
                event,
                stage=stage,
                attempts=attempts,
                detail=detail,
                recovery=recovery,
            )
        else:
            self.notifier.final_combined(event, success=False, detail=detail)

    def _notify_operational_alerts(self) -> None:
        method = getattr(self.notifier, "operational_alert", None) if self.notifier else None
        if not callable(method):
            return
        from .dashboard.data import DashboardData

        data = DashboardData.from_records(
            [],
            operational_events=self.state.list_event_rows(),
            job_runs=self.state.list_job_runs(),
            poll_cycles=self.state.list_poll_cycles(),
            artifact_publications=self.state.list_artifact_publications(),
        )
        for alert in data.operational_alerts(
            now=self.clock(),
            stuck_after_seconds=self.config.stuck_event_seconds,
            repeated_failure_threshold=self.config.repeated_failure_threshold,
        ):
            method(alert)

    def discover(self, *, since: datetime, until: datetime) -> int:
        discovered = 0
        for event in self.event_provider.list_events(
            self.config.tickers, since=since, until=until
        ):
            existing = self.state.get_event(event.provider_event_id)
            if existing is None:
                period_match = self.state.get_event_for_period(
                    event.ticker, event.fiscal_period
                )
                if period_match is not None:
                    if not period_match.manual_override:
                        LOG.warning(
                            "Ignoring provider event ID change for %s %s: %s -> %s",
                            event.ticker,
                            event.fiscal_period,
                            period_match.event.provider_event_id,
                            event.provider_event_id,
                        )
                    continue
                self.state.upsert_event(MonitoredEvent(event=event))
                discovered += 1
            elif not existing.manual_override and existing.event != event:
                # Provider schedule corrections update only event metadata. The
                # lifecycle, transcript observation, and queued jobs remain intact.
                existing.event = event
                existing.updated_at = self.clock()
                self.state.upsert_event(existing)
                discovered += 1
        return discovered

    def _enqueue_stage(
        self,
        monitored: MonitoredEvent,
        *,
        stage: str,
        target: EventState,
        payload: dict | None = None,
    ) -> bool:
        inserted = self.state.enqueue(
            idempotency_key=(
                f"{monitored.event.provider_event_id}:{stage}:"
                f"{(payload or {}).get('fingerprint', 'v1')}"
            ),
            provider_event_id=monitored.event.provider_event_id,
            payload={"stage": stage, **(payload or {})},
            max_attempts=self.config.max_job_attempts,
            available_at=self.clock(),
        )
        monitored.transition(target)
        self.state.upsert_event(monitored)
        return inserted

    def _observe_transcript_while_quant_runs(
        self, monitored: MonitoredEvent, *, now: datetime
    ) -> None:
        """Capture and stabilize transcripts without waiting for quant completion."""
        poll_at = monitored.event.call_at + timedelta(
            seconds=self.config.transcript_start_delay_seconds
        )
        timeout_at = monitored.event.call_at + timedelta(
            seconds=self.config.transcript_timeout_seconds
        )
        if now < poll_at:
            return
        if now > timeout_at:
            monitored.last_error = (
                "transcript unavailable before "
                f"{self.config.transcript_timeout_seconds}-second timeout"
            )
            self.state.upsert_event(monitored)
            return
        document = self.transcript_provider.get_transcript(monitored.event)
        if document is None:
            return
        decision = self.stabilizer.assess(
            document,
            previous_fingerprint=monitored.transcript_fingerprint,
            first_observed_at=monitored.transcript_observed_at,
            now=now,
        )
        monitored.transcript_fingerprint = decision.fingerprint
        monitored.transcript_observed_at = decision.first_observed_at
        self.state.upsert_event(monitored)

    def advance_events(self) -> int:
        """Advance lifecycle gates and enqueue only the next legal stage."""
        now = self.clock()
        queued = 0
        candidates = self.state.list_events()
        for monitored in candidates:
            if monitored.state in {
                EventState.AWAITING_RELEASE,
                EventState.AWAITING_QUANT_DATA,
                EventState.QUANT_QUEUED,
                EventState.QUANT_RUNNING,
            }:
                self._observe_transcript_while_quant_runs(monitored, now=now)

            if monitored.state == EventState.SCHEDULED:
                queued += self._enqueue_stage(
                    monitored, stage="pre_release", target=EventState.BASELINE_QUEUED
                )
                continue

            if monitored.state == EventState.AWAITING_RELEASE:
                quant_poll_at = max(
                    monitored.event.report_at,
                    monitored.event.call_at
                    - timedelta(seconds=self.config.quant_start_offset_seconds),
                )
                if now >= quant_poll_at:
                    monitored.transition(EventState.AWAITING_QUANT_DATA)
                    self.state.upsert_event(monitored)
                continue

            if monitored.state == EventState.AWAITING_QUANT_DATA:
                freshness = self.freshness.check(
                    monitored.event.ticker, monitored.event.fiscal_period
                )
                if not freshness.is_fresh:
                    monitored.last_error = f"waiting for expected-quarter data: {freshness.detail}"
                    self.state.upsert_event(monitored)
                    continue
                queued += self._enqueue_stage(
                    monitored,
                    stage="release_to_call",
                    target=EventState.QUANT_QUEUED,
                    payload={
                        "freshness": {
                            "as_of": freshness.as_of.isoformat()
                            if freshness.as_of
                            else None,
                            "detail": freshness.detail,
                        }
                    },
                )
                continue

            if (
                monitored.state == EventState.FAILED
                and monitored.last_error
                and monitored.last_error.startswith("transcript unavailable before")
                and self.transcript_provider.get_transcript(monitored.event) is not None
            ):
                monitored.transition(EventState.TRANSCRIPT_PENDING)
                self.state.upsert_event(monitored)
                continue

            if monitored.state == EventState.AWAITING_CALL:
                transcript_poll_at = monitored.event.call_at + timedelta(
                    seconds=self.config.transcript_start_delay_seconds
                )
                transcript_timeout_at = monitored.event.call_at + timedelta(
                    seconds=self.config.transcript_timeout_seconds
                )
                document = (
                    self.transcript_provider.get_transcript(monitored.event)
                    if now >= transcript_poll_at
                    else None
                )
                if document is not None or (
                    now >= transcript_poll_at and now <= transcript_timeout_at
                ):
                    monitored.transition(EventState.TRANSCRIPT_PENDING)
                    self.state.upsert_event(monitored)
                elif now > transcript_timeout_at:
                    message = (
                        "transcript unavailable before "
                        f"{self.config.transcript_timeout_seconds}-second timeout"
                    )
                    monitored.transition(EventState.FAILED, error=message)
                    self.state.upsert_event(monitored)
                    self._notify_failure(
                        monitored.event,
                        stage="transcript_wait",
                        attempts=0,
                        detail=message,
                        recovery="Confirm transcript delivery/provider access, then let the monitor resume the persisted event.",
                    )
                continue

            if monitored.state not in {
                EventState.TRANSCRIPT_PENDING,
                EventState.TRANSCRIPT_UNSTABLE,
                EventState.COMPLETE,
            }:
                continue
            document = self.transcript_provider.get_transcript(monitored.event)
            if document is None and (
                monitored.state != EventState.COMPLETE
                and now
                > monitored.event.call_at
                + timedelta(seconds=self.config.transcript_timeout_seconds)
            ):
                message = (
                    "transcript unavailable before "
                    f"{self.config.transcript_timeout_seconds}-second timeout"
                )
                monitored.transition(EventState.FAILED, error=message)
                self.state.upsert_event(monitored)
                self._notify_failure(
                    monitored.event,
                    stage="transcript_wait",
                    attempts=0,
                    detail=message,
                    recovery="Confirm transcript delivery/provider access, then let the monitor resume the persisted event.",
                )
                continue
            if document is None:
                continue
            fingerprint_before = monitored.transcript_fingerprint
            decision = self.stabilizer.assess(
                document,
                previous_fingerprint=monitored.transcript_fingerprint,
                first_observed_at=monitored.transcript_observed_at,
                now=now,
            )
            monitored.transcript_fingerprint = decision.fingerprint
            monitored.transcript_observed_at = decision.first_observed_at
            if monitored.state == EventState.COMPLETE:
                if fingerprint_before == decision.fingerprint:
                    continue
                monitored.transition(EventState.TRANSCRIPT_UNSTABLE)
                self.state.upsert_event(monitored)
                continue
            if not decision.ready:
                if monitored.state == EventState.TRANSCRIPT_PENDING:
                    monitored.transition(EventState.TRANSCRIPT_UNSTABLE)
                elif monitored.state == EventState.TRANSCRIPT_UNSTABLE:
                    monitored.transition(EventState.TRANSCRIPT_UNSTABLE)
                self.state.upsert_event(monitored)
                continue
            if monitored.state == EventState.TRANSCRIPT_PENDING:
                monitored.transition(EventState.TRANSCRIPT_UNSTABLE)
            queued += self._enqueue_stage(
                monitored,
                stage="post_call",
                target=EventState.POST_CALL_QUEUED,
                payload={"fingerprint": decision.fingerprint},
            )
        return queued

    def poll_transcripts(self) -> int:
        """Compatibility name for one full lifecycle advancement pass."""
        return self.advance_events()

    def run_next_job(self) -> bool:
        job = self.state.claim_next_job(self.clock())
        if job is None:
            processed = self._run_next_artifact_publication()
            if not processed:
                self._notify_operational_alerts()
            return processed
        stage = str(job["payload"].get("stage") or "unknown")
        run_id = self.state.start_job_run(job, stage=stage, started_at=self.clock())
        monitored = self.state.get_event(job["provider_event_id"])
        if monitored is None:
            self.state.finish_job(job["id"], success=False, error="event missing")
            self.state.finish_job_run(
                run_id, error="event missing", finished_at=self.clock()
            )
            return True
        running_state = {
            "pre_release": EventState.BASELINE_RUNNING,
            "release_to_call": EventState.QUANT_RUNNING,
            "post_call": EventState.POST_CALL_RUNNING,
        }.get(stage)
        if running_state is None:
            self.state.finish_job(job["id"], success=False, error=f"unknown stage {stage!r}")
            self.state.finish_job_run(
                run_id, error=f"unknown stage {stage!r}", finished_at=self.clock()
            )
            return True
        monitored.transition(running_state)
        self.state.upsert_event(monitored)
        try:
            transcript = None
            if stage == "post_call":
                transcript = self.transcript_provider.get_transcript(monitored.event)
                if transcript is None:
                    raise RuntimeError("transcript disappeared before post-call processing")
                actual = self.stabilizer.assess(
                    transcript,
                    previous_fingerprint=job["payload"]["fingerprint"],
                    first_observed_at=monitored.transcript_observed_at,
                    now=self.clock(),
                )
                if actual.fingerprint != job["payload"]["fingerprint"]:
                    self.state.finish_job(job["id"], success=True)
                    self.state.finish_job_run(
                        run_id,
                        status="superseded",
                        result={"observed_fingerprint": actual.fingerprint},
                        finished_at=self.clock(),
                    )
                    monitored.transcript_fingerprint = actual.fingerprint
                    monitored.transcript_observed_at = self.clock()
                    monitored.transition(EventState.TRANSCRIPT_UNSTABLE)
                    self.state.upsert_event(monitored)
                    return True
            result = dict(self.workflow.run(stage, monitored.event, transcript) or {})
            if stage == "release_to_call" and job["payload"].get("freshness"):
                result["freshness"] = job["payload"]["freshness"]
            history_refresh = self._refresh_history_dataset()
            if history_refresh is not None:
                result["history_refresh"] = history_refresh
            self.state.finish_job(job["id"], success=True)
            target = {
                "pre_release": EventState.AWAITING_RELEASE,
                "release_to_call": EventState.AWAITING_CALL,
                "post_call": EventState.COMPLETE,
            }[stage]
            monitored.transition(target)
            self.state.upsert_event(monitored)
            completed_at = self.clock().astimezone(timezone.utc).isoformat()
            self.state.finish_job_run(
                run_id,
                result=result,
                finished_at=self.clock(),
            )
            if (
                stage == "post_call"
                and self.artifact_publisher is not None
                and monitored.transcript_fingerprint
            ):
                fingerprint = monitored.transcript_fingerprint
                self.state.enqueue_artifact_publication(
                    publication_key=(
                        f"{monitored.event.provider_event_id}:{fingerprint}"
                    ),
                    provider_event_id=monitored.event.provider_event_id,
                    fingerprint=fingerprint,
                    payload={
                        "workflow_result": result,
                        "completed_at": completed_at,
                    },
                    max_attempts=self.config.r2_publish_max_attempts,
                    available_at=self.clock(),
                )
            if self.notifier and stage == "release_to_call":
                self.notifier.pre_call_quant(monitored.event, detail=str(result or ""))
            elif self.notifier and stage == "post_call":
                self.notifier.final_combined(
                    monitored.event,
                    success=True,
                    detail=f"quant=reused; post_call={result or ''}",
                )
        except Exception as exc:
            LOG.exception("Workflow failed for %s", monitored.event.provider_event_id)
            retry_delay = timedelta(
                seconds=self.config.retry_base_seconds
                * (2 ** max(job["attempts"] - 1, 0))
            )
            self.state.finish_job(
                job["id"],
                success=False,
                error=str(exc),
                retry_delay=retry_delay,
            )
            self.state.finish_job_run(
                run_id, error=str(exc), finished_at=self.clock()
            )
            monitored.transition(EventState.FAILED, error=str(exc))
            if job["attempts"] < job["max_attempts"]:
                retry_state = {
                    "pre_release": EventState.BASELINE_QUEUED,
                    "release_to_call": EventState.QUANT_QUEUED,
                    "post_call": EventState.POST_CALL_QUEUED,
                }[stage]
                monitored.transition(retry_state)
            self.state.upsert_event(monitored)
            if job["attempts"] >= job["max_attempts"]:
                self._notify_failure(
                    monitored.event,
                    stage=stage,
                    attempts=job["attempts"],
                    detail=str(exc),
                )
        return True

    def _run_next_artifact_publication(self) -> bool:
        if self.artifact_publisher is None:
            return False
        publication = self.state.claim_artifact_publication(self.clock())
        if publication is None:
            return False
        monitored = self.state.get_event(publication["provider_event_id"])
        if monitored is None:
            self.state.finish_artifact_publication(
                publication["id"],
                success=False,
                error="event missing",
                finished_at=self.clock(),
            )
            return True
        try:
            result = self.artifact_publisher.publish(
                event=monitored.event,
                fingerprint=publication["fingerprint"],
                workflow_result=publication["payload"]["workflow_result"],
                completed_at=publication["payload"]["completed_at"],
            )
            manifest = getattr(result, "manifest", None)
            self.state.finish_artifact_publication(
                publication["id"],
                success=True,
                manifest_uri=getattr(manifest, "uri", None),
                finished_at=self.clock(),
            )
        except Exception as exc:
            LOG.exception(
                "Artifact publication failed for %s",
                publication["provider_event_id"],
            )
            retry_delay = timedelta(
                seconds=self.config.retry_base_seconds
                * (2 ** max(publication["attempts"] - 1, 0))
            )
            self.state.finish_artifact_publication(
                publication["id"],
                success=False,
                error=str(exc),
                retry_delay=retry_delay,
                finished_at=self.clock(),
            )
        return True

    def run_cycle(
        self,
        *,
        lookback: timedelta = timedelta(days=2),
        lookahead: timedelta = timedelta(days=30),
        process_jobs: bool = True,
    ) -> dict:
        now = self.clock()
        cycle_id = self.state.start_poll_cycle(now)
        try:
            discovered = self.discover(since=now - lookback, until=now + lookahead)
            queued = self.advance_events()
            jobs = 0
            if process_jobs:
                while self.run_next_job():
                    jobs += 1
            result = {"discovered": discovered, "queued": queued, "jobs": jobs}
            self.state.finish_poll_cycle(
                cycle_id, result=result, finished_at=self.clock()
            )
            self._notify_operational_alerts()
            return result
        except Exception as exc:
            self.state.finish_poll_cycle(
                cycle_id, error=str(exc), finished_at=self.clock()
            )
            raise
