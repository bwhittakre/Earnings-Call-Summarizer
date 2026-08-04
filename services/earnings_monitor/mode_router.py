"""Classify earnings-monitor workflow mode and history lookback window."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

WorkflowMode = Literal["first_print", "onboard", "standard"]

LOOKBACK_DECISION_HOURS = 48
LOOKBACK_YEARS_LONG = 10
LOOKBACK_YEARS_SHORT = 3


@dataclass(frozen=True)
class ModeDecision:
    mode: WorkflowMode
    reason: str
    lookback_years: int | None = None
    prior_event_count: int = 0
    on_disk_transcript_count: int = 0


def choose_lookback_years(
    report_at: datetime,
    *,
    now: datetime | None = None,
) -> int:
    """Return 10y when report is ≥48h away, else 3y.

    Both timestamps must be timezone-aware. Naive values are treated as UTC.
    """
    current = now or datetime.now(timezone.utc)
    report = report_at if report_at.tzinfo else report_at.replace(tzinfo=timezone.utc)
    current = current if current.tzinfo else current.replace(tzinfo=timezone.utc)
    lead = report.astimezone(timezone.utc) - current.astimezone(timezone.utc)
    if lead >= timedelta(hours=LOOKBACK_DECISION_HOURS):
        return LOOKBACK_YEARS_LONG
    return LOOKBACK_YEARS_SHORT


def classify_workflow_mode(
    *,
    prior_event_count: int = 0,
    on_disk_transcript_count: int = 0,
    in_company_registry: bool = False,
    has_scored_history: bool = False,
    report_at: datetime | None = None,
    now: datetime | None = None,
) -> ModeDecision:
    """Map ticker+period readiness signals to first_print | onboard | standard.

    Priority:
    1. Zero prior Quartr/ROIC events *and* no on-disk transcripts → first_print
    2. Already registered with scored history → standard
    3. Otherwise → onboard (has prior history or partial local setup)
    """
    prior = max(0, int(prior_event_count))
    on_disk = max(0, int(on_disk_transcript_count))
    lookback = (
        choose_lookback_years(report_at, now=now) if report_at is not None else None
    )

    if prior == 0 and on_disk == 0:
        return ModeDecision(
            mode="first_print",
            reason=(
                "No prior Quartr/ROIC earnings events and no on-disk transcripts; "
                "use First-Print (arm --first-print) instead of Onboard."
            ),
            lookback_years=lookback,
            prior_event_count=prior,
            on_disk_transcript_count=on_disk,
        )

    if in_company_registry and has_scored_history and on_disk > 0:
        return ModeDecision(
            mode="standard",
            reason="Company is registered with scored history and local transcripts.",
            lookback_years=lookback,
            prior_event_count=prior,
            on_disk_transcript_count=on_disk,
        )

    if prior == 0 and on_disk > 0:
        reason = (
            "Local transcripts exist but providers report zero prior events; "
            "prefer Onboard to scaffold history from disk."
        )
    elif not in_company_registry:
        reason = "Prior history exists but ticker is not in CompanyProfile registry."
    elif not has_scored_history:
        reason = "Company is registered but scored history / feature panel is incomplete."
    else:
        reason = "Prior history available; run Onboard to finish monitor readiness."

    return ModeDecision(
        mode="onboard",
        reason=reason,
        lookback_years=lookback,
        prior_event_count=prior,
        on_disk_transcript_count=on_disk,
    )


def classify_ticker_period(
    ticker: str,
    fiscal_period: str,
    *,
    prior_event_count: int = 0,
    on_disk_transcript_count: int = 0,
    in_company_registry: bool = False,
    has_scored_history: bool = False,
    report_at: datetime | None = None,
    now: datetime | None = None,
) -> ModeDecision:
    """Convenience wrapper; ticker/period are validated only for non-empty values."""
    del fiscal_period  # classification is period-agnostic given counts
    if not str(ticker).strip():
        raise ValueError("ticker is required")
    return classify_workflow_mode(
        prior_event_count=prior_event_count,
        on_disk_transcript_count=on_disk_transcript_count,
        in_company_registry=in_company_registry,
        has_scored_history=has_scored_history,
        report_at=report_at,
        now=now,
    )
