"""Polling and idempotent job orchestration for the local monitor."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Protocol

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
        clock=None,
    ):
        self.config = config
        self.state = state
        self.event_provider = event_provider
        self.transcript_provider = transcript_provider
        self.freshness = freshness
        self.workflow = workflow
        self.notifier = notifier
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.stabilizer = TranscriptStabilizer(
            stable_for=timedelta(seconds=config.stabilization_seconds),
            minimum_chars=config.minimum_transcript_chars,
        )

    def discover(self, *, since: datetime, until: datetime) -> int:
        discovered = 0
        for event in self.event_provider.list_events(
            self.config.tickers, since=since, until=until
        ):
            existing = self.state.get_event(event.provider_event_id)
            if existing is None:
                self.state.upsert_event(MonitoredEvent(event=event))
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

    def advance_events(self) -> int:
        """Advance lifecycle gates and enqueue only the next legal stage."""
        now = self.clock()
        queued = 0
        candidates = self.state.list_events()
        for monitored in candidates:
            if monitored.state == EventState.SCHEDULED:
                queued += self._enqueue_stage(
                    monitored, stage="pre_release", target=EventState.BASELINE_QUEUED
                )
                continue

            if monitored.state == EventState.AWAITING_RELEASE:
                if now >= monitored.event.report_at:
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
                    monitored, stage="release_to_call", target=EventState.QUANT_QUEUED
                )
                continue

            if monitored.state == EventState.AWAITING_CALL:
                if now >= monitored.event.call_at:
                    monitored.transition(EventState.TRANSCRIPT_PENDING)
                    self.state.upsert_event(monitored)
                continue

            if monitored.state not in {
                EventState.TRANSCRIPT_PENDING,
                EventState.TRANSCRIPT_UNSTABLE,
                EventState.COMPLETE,
            }:
                continue
            document = self.transcript_provider.get_transcript(monitored.event)
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
            return False
        monitored = self.state.get_event(job["provider_event_id"])
        if monitored is None:
            self.state.finish_job(job["id"], success=False, error="event missing")
            return True
        stage = job["payload"].get("stage")
        running_state = {
            "pre_release": EventState.BASELINE_RUNNING,
            "release_to_call": EventState.QUANT_RUNNING,
            "post_call": EventState.POST_CALL_RUNNING,
        }.get(stage)
        if running_state is None:
            self.state.finish_job(job["id"], success=False, error=f"unknown stage {stage!r}")
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
                    monitored.transcript_fingerprint = actual.fingerprint
                    monitored.transcript_observed_at = self.clock()
                    monitored.transition(EventState.TRANSCRIPT_UNSTABLE)
                    self.state.upsert_event(monitored)
                    return True
            result = self.workflow.run(stage, monitored.event, transcript)
            self.state.finish_job(job["id"], success=True)
            target = {
                "pre_release": EventState.AWAITING_RELEASE,
                "release_to_call": EventState.AWAITING_CALL,
                "post_call": EventState.COMPLETE,
            }[stage]
            monitored.transition(target)
            self.state.upsert_event(monitored)
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
            self.state.finish_job(job["id"], success=False, error=str(exc))
            monitored.transition(EventState.FAILED, error=str(exc))
            if job["attempts"] < job["max_attempts"]:
                retry_state = {
                    "pre_release": EventState.BASELINE_QUEUED,
                    "release_to_call": EventState.QUANT_QUEUED,
                    "post_call": EventState.POST_CALL_QUEUED,
                }[stage]
                monitored.transition(retry_state)
            self.state.upsert_event(monitored)
            if (
                stage == "post_call"
                and job["attempts"] >= job["max_attempts"]
                and self.notifier
            ):
                self.notifier.final_combined(
                    monitored.event, success=False, detail=str(exc)
                )
        return True

    def run_cycle(self, *, lookback: timedelta = timedelta(days=2), lookahead: timedelta = timedelta(days=30)) -> dict:
        now = self.clock()
        discovered = self.discover(since=now - lookback, until=now + lookahead)
        queued = self.advance_events()
        jobs = 0
        while self.run_next_job():
            jobs += 1
        return {"discovered": discovered, "queued": queued, "jobs": jobs}
