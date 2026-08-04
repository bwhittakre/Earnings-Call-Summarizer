"""Domain objects and the explicit event state machine."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EventState(StrEnum):
    SCHEDULED = "scheduled"
    ONBOARDING = "onboarding"
    ONBOARDING_BLOCKED = "onboarding_blocked"
    BASELINE_QUEUED = "baseline_queued"
    BASELINE_RUNNING = "baseline_running"
    AWAITING_RELEASE = "awaiting_release"
    AWAITING_QUANT_DATA = "awaiting_quant_data"
    QUANT_QUEUED = "quant_queued"
    QUANT_RUNNING = "quant_running"
    AWAITING_CALL = "awaiting_call"
    TRANSCRIPT_PENDING = "transcript_pending"
    TRANSCRIPT_UNSTABLE = "transcript_unstable"
    POST_CALL_QUEUED = "post_call_queued"
    POST_CALL_RUNNING = "post_call_running"
    COMPLETE = "complete"
    FAILED = "failed"


class WorkflowMode(StrEnum):
    STANDARD = "standard"
    ONBOARD = "onboard"
    FIRST_PRINT = "first_print"


class TranscriptStatus(StrEnum):
    LIVE = "live"
    FINAL = "final"


TERMINAL_STATES = frozenset({EventState.COMPLETE})
TRANSITIONS: dict[EventState, frozenset[EventState]] = {
    EventState.SCHEDULED: frozenset(
        {
            EventState.BASELINE_QUEUED,
            EventState.AWAITING_RELEASE,
            EventState.ONBOARDING,
        }
    ),
    EventState.ONBOARDING: frozenset(
        {
            EventState.SCHEDULED,
            EventState.ONBOARDING_BLOCKED,
            EventState.FAILED,
        }
    ),
    EventState.ONBOARDING_BLOCKED: frozenset(
        {
            EventState.ONBOARDING,
            EventState.SCHEDULED,
            EventState.FAILED,
        }
    ),
    EventState.BASELINE_QUEUED: frozenset({EventState.BASELINE_RUNNING, EventState.FAILED}),
    EventState.BASELINE_RUNNING: frozenset({EventState.AWAITING_RELEASE, EventState.FAILED}),
    EventState.AWAITING_RELEASE: frozenset({EventState.AWAITING_QUANT_DATA}),
    EventState.AWAITING_QUANT_DATA: frozenset({EventState.QUANT_QUEUED}),
    EventState.QUANT_QUEUED: frozenset({EventState.QUANT_RUNNING, EventState.FAILED}),
    EventState.QUANT_RUNNING: frozenset({EventState.AWAITING_CALL, EventState.FAILED}),
    EventState.AWAITING_CALL: frozenset(
        {EventState.TRANSCRIPT_PENDING, EventState.FAILED}
    ),
    EventState.TRANSCRIPT_PENDING: frozenset(
        {EventState.TRANSCRIPT_UNSTABLE, EventState.FAILED}
    ),
    EventState.TRANSCRIPT_UNSTABLE: frozenset(
        {
            EventState.TRANSCRIPT_UNSTABLE,
            EventState.POST_CALL_QUEUED,
            EventState.FAILED,
        }
    ),
    EventState.POST_CALL_QUEUED: frozenset({EventState.POST_CALL_RUNNING, EventState.FAILED}),
    EventState.POST_CALL_RUNNING: frozenset(
        {EventState.COMPLETE, EventState.TRANSCRIPT_UNSTABLE, EventState.FAILED}
    ),
    # A provider revision after completion is stabilized and processed with a
    # new fingerprinted job, while notification keys remain one-shot.
    EventState.COMPLETE: frozenset({EventState.TRANSCRIPT_UNSTABLE}),
    EventState.FAILED: frozenset(
        {
            EventState.BASELINE_QUEUED,
            EventState.QUANT_QUEUED,
            EventState.TRANSCRIPT_PENDING,
            EventState.POST_CALL_QUEUED,
            EventState.ONBOARDING,
            EventState.SCHEDULED,
        }
    ),
}


class InvalidTransition(ValueError):
    pass


@dataclass(frozen=True)
class EarningsEvent:
    provider_event_id: str
    ticker: str
    fiscal_period: str
    report_at: datetime
    call_at: datetime
    title: str = ""
    source_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", self.ticker.strip().upper())
        object.__setattr__(self, "fiscal_period", self.fiscal_period.strip().upper())
        if not self.provider_event_id.strip():
            raise ValueError("provider_event_id is required")
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", self.ticker):
            raise ValueError(f"invalid ticker {self.ticker!r}")
        if not re.fullmatch(r"FY\d{4}-Q[1-4]", self.fiscal_period):
            raise ValueError(f"invalid fiscal_period {self.fiscal_period!r}")
        if self.report_at.tzinfo is None or self.call_at.tzinfo is None:
            raise ValueError("report_at and call_at must be timezone-aware")
        if self.call_at < self.report_at:
            raise ValueError("call_at cannot precede report_at")

    @property
    def scheduled_at(self) -> datetime:
        """Compatibility alias: the operational event is scheduled for its call."""
        return self.call_at


@dataclass
class MonitoredEvent:
    event: EarningsEvent
    state: EventState = EventState.SCHEDULED
    transcript_fingerprint: str | None = None
    transcript_observed_at: datetime | None = None
    last_error: str | None = None
    updated_at: datetime = field(default_factory=utc_now)
    manual_override: bool = False
    workflow_mode: str = WorkflowMode.STANDARD.value
    first_print: bool = False

    def transition(self, target: EventState, *, error: str | None = None) -> None:
        if target == self.state and target == EventState.TRANSCRIPT_UNSTABLE:
            self.updated_at = utc_now()
            return
        if target not in TRANSITIONS[self.state]:
            raise InvalidTransition(f"Cannot transition {self.state.value} -> {target.value}")
        self.state = target
        self.last_error = error
        self.updated_at = utc_now()


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class TranscriptDocument:
    ticker: str
    fiscal_period: str
    content: str
    source_name: str
    source_id: str
    observed_at: datetime = field(default_factory=utc_now)
    source_url: str | None = None
    provider_event_id: str | None = None
    status: TranscriptStatus = TranscriptStatus.FINAL

    def __post_init__(self) -> None:
        object.__setattr__(self, "ticker", self.ticker.strip().upper())
        object.__setattr__(self, "fiscal_period", self.fiscal_period.strip().upper())
        object.__setattr__(self, "status", TranscriptStatus(self.status))
        if not self.source_id.strip():
            raise ValueError("source_id is required")
        if not re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", self.ticker):
            raise ValueError(f"invalid ticker {self.ticker!r}")
        if not re.fullmatch(r"FY\d{4}-Q[1-4]", self.fiscal_period):
            raise ValueError(f"invalid fiscal_period {self.fiscal_period!r}")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
