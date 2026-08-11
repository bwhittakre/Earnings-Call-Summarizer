"""Shared ops helpers: state-aware stuck detection, host health, ranks/research alerts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

UTC = timezone.utc

PRE_CALL_WAIT_STATES = frozenset(
    {
        "awaiting_release",
        "awaiting_quant_data",
        "awaiting_call",
    }
)
TERMINAL_STATES = frozenset(
    {
        "complete",
        "failed",
        "onboarding",
        "onboarding_blocked",
    }
)

DEFAULT_PRE_CALL_GRACE_SECONDS = 30 * 60
DEFAULT_HOST_STALE_SECONDS = 30 * 60
DEFAULT_RESEARCH_STALE_MULTIPLIER = 3
DEFAULT_ASOF_GRACE_SECONDS = 6 * 60 * 60


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def age_seconds(value: Any, now: datetime) -> int | None:
    stamped = _parse_dt(value)
    if stamped is None:
        return None
    return max(0, int((now - stamped).total_seconds()))


def pre_call_grace_seconds() -> int:
    return int(
        os.environ.get(
            "EARNINGS_MONITOR_PRE_CALL_GRACE_SECONDS",
            str(DEFAULT_PRE_CALL_GRACE_SECONDS),
        )
    )


def event_is_stuck(
    event: Mapping[str, Any],
    *,
    now: datetime,
    stuck_after_seconds: int,
    grace_seconds: int | None = None,
) -> tuple[bool, str | None]:
    """Return (stuck, detail). Pre-call waits are schedule-relative."""
    state = str(event.get("state") or event.get("status") or "")
    if state in TERMINAL_STATES:
        return False, None
    age = age_seconds(event.get("updated_at"), now)
    grace = pre_call_grace_seconds() if grace_seconds is None else grace_seconds
    call_at = _parse_dt(event.get("call_at") or event.get("scheduled_at"))
    report_at = _parse_dt(event.get("report_at"))

    if state in PRE_CALL_WAIT_STATES:
        # Healthy wait until call_at (+ grace). Prefer call_at; else report_at.
        anchor = call_at or report_at
        if anchor is None:
            if age is not None and age >= stuck_after_seconds:
                return True, f"pre-call wait unchanged for {age}s (no schedule)"
            return False, None
        due = anchor + timedelta(seconds=grace)
        if now <= due:
            return False, None
        overdue = int((now - due).total_seconds())
        return True, (
            f"still {state} {overdue}s after schedule+grace "
            f"(call_at={anchor.isoformat()})"
        )

    # Running / transcript / queued post-call: wall-clock inactivity.
    if age is not None and age >= stuck_after_seconds:
        return True, f"event unchanged for {age} seconds in state={state}"
    return False, None


def default_host_health_path(repo_root: Path | str) -> Path:
    return Path(repo_root) / "host_quartr" / "health" / "last_run.json"


def write_host_health(
    path: Path | str,
    *,
    job: str,
    ok: bool,
    started_at: datetime,
    finished_at: datetime,
    counts: Mapping[str, Any] | None = None,
    failures: list[dict[str, Any]] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "job": job,
        "ok": bool(ok),
        "started_at": started_at.astimezone(UTC).isoformat(),
        "finished_at": finished_at.astimezone(UTC).isoformat(),
        "counts": dict(counts or {}),
        "failures": list(failures or []),
    }
    if extra:
        payload.update(dict(extra))
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return target


def load_host_health(path: Path | str | None) -> dict[str, Any] | None:
    if path is None:
        return None
    target = Path(path)
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def resolve_host_health_path(
    *,
    repo_root: Path | str | None = None,
    explicit: Path | str | None = None,
) -> Path | None:
    if explicit is not None:
        return Path(explicit)
    env = os.environ.get("EARNINGS_MONITOR_HOST_HEALTH_PATH")
    if env:
        return Path(env)
    if repo_root is not None:
        return default_host_health_path(repo_root)
    cwd_candidate = Path.cwd() / "host_quartr" / "health" / "last_run.json"
    return cwd_candidate if cwd_candidate.is_file() else cwd_candidate


def host_health_alerts(
    health: Mapping[str, Any] | None,
    *,
    now: datetime,
    stale_after_seconds: int | None = None,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if health is None:
        return alerts
    stale_after = stale_after_seconds or int(
        os.environ.get(
            "EARNINGS_MONITOR_HOST_STALE_SECONDS",
            str(DEFAULT_HOST_STALE_SECONDS),
        )
    )
    finished = health.get("finished_at") or health.get("started_at")
    age = age_seconds(finished, now)
    if age is not None and age >= stale_after:
        alerts.append(
            {
                "kind": "host_feed_stale",
                "severity": "warning",
                "occurrence": finished,
                "age_seconds": age,
                "detail": (
                    f"host {health.get('job') or 'job'} last finished {age}s ago"
                ),
            }
        )
    if health.get("ok") is False:
        failures = health.get("failures") or []
        missing = [
            row
            for row in failures
            if isinstance(row, dict)
            and str(row.get("skipped_reason") or row.get("error") or "")
            == "missing_dump"
        ]
        if missing:
            sample = missing[0]
            alerts.append(
                {
                    "kind": "host_missing_dump",
                    "severity": "error",
                    "provider_event_id": sample.get("event_id"),
                    "ticker": sample.get("ticker"),
                    "occurrence": finished,
                    "failures": len(missing),
                    "detail": f"{len(missing)} missing transcript dump(s) near call",
                }
            )
        else:
            alerts.append(
                {
                    "kind": "host_dispatch_failed",
                    "severity": "error",
                    "occurrence": finished,
                    "detail": (
                        f"host {health.get('job') or 'job'} failed: "
                        f"{len(failures)} failure(s)"
                    ),
                    "failures": len(failures),
                }
            )
    return alerts


def research_freshness_alerts(
    *,
    dirty: Mapping[str, Any] | None,
    last_regen: Mapping[str, Any] | None,
    now: datetime,
    debounce_seconds: int = 60,
    idle_seconds: int = 30,
    universe_stale_message: str | None = None,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    threshold = max(
        300,
        DEFAULT_RESEARCH_STALE_MULTIPLIER * (int(debounce_seconds) + int(idle_seconds)),
    )
    if dirty:
        age = age_seconds(dirty.get("marked_at"), now)
        if age is not None and age >= threshold:
            alerts.append(
                {
                    "kind": "research_book_stale",
                    "severity": "warning",
                    "occurrence": dirty.get("marked_at"),
                    "age_seconds": age,
                    "detail": (
                        f"research book dirty for {age}s "
                        f"(reason={dirty.get('reason') or 'unknown'})"
                    ),
                }
            )
    if last_regen and last_regen.get("ok") is False and dirty:
        alerts.append(
            {
                "kind": "research_book_stale",
                "severity": "error",
                "occurrence": last_regen.get("finished_at") or dirty.get("marked_at"),
                "detail": "last research regen failed and book is still dirty",
            }
        )
    if universe_stale_message:
        alerts.append(
            {
                "kind": "research_universe_stale",
                "severity": "warning",
                "occurrence": now.isoformat(),
                "detail": universe_stale_message,
            }
        )
    return alerts


def book_ranks_summary_alerts(
    summary: Mapping[str, Any] | None,
    *,
    now: datetime,
    asof_grace_seconds: int | None = None,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    if not summary:
        return alerts
    reason = summary.get("skipped_reason")
    if reason in {"below_min_names", "no_panels", "no_rank_rows"}:
        alerts.append(
            {
                "kind": "book_ranks_thin_peers",
                "severity": "warning",
                "occurrence": summary.get("built_at"),
                "detail": (
                    f"book ranks skipped ({reason}); "
                    f"n_peers={summary.get('n_peers')} "
                    f"bucket={summary.get('period_bucket')}"
                ),
            }
        )
    if reason == "awaiting_investable_asof" or summary.get("pending"):
        as_of = _parse_dt(summary.get("as_of_date"))
        grace = asof_grace_seconds or int(
            os.environ.get(
                "EARNINGS_MONITOR_BOOK_RANKS_ASOF_GRACE_SECONDS",
                str(DEFAULT_ASOF_GRACE_SECONDS),
            )
        )
        if as_of is not None and now > as_of + timedelta(seconds=grace):
            alerts.append(
                {
                    "kind": "book_ranks_asof_overdue",
                    "severity": "warning",
                    "occurrence": summary.get("as_of_date"),
                    "detail": (
                        f"investable-asof ranks still pending after as_of="
                        f"{summary.get('as_of_date')} + grace"
                    ),
                }
            )
    if summary.get("last_error") or summary.get("ok") is False:
        alerts.append(
            {
                "kind": "book_ranks_failed",
                "severity": "error",
                "occurrence": summary.get("built_at"),
                "detail": str(
                    summary.get("last_error") or "book ranks subprocess failed"
                ),
            }
        )
    return alerts


def load_book_ranks_summary(
    *,
    history_source: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any] | None:
    candidates: list[Path] = []
    if history_source is not None:
        root = Path(history_source)
        if root.name == "cross_company":
            candidates.append(root / "json" / "book_ranks_summary.json")
        else:
            candidates.append(root / "cross_company" / "json" / "book_ranks_summary.json")
            candidates.append(root / "json" / "book_ranks_summary.json")
    if repo_root is not None:
        candidates.append(
            Path(repo_root)
            / "Structured Narrative"
            / "output"
            / "cross_company"
            / "json"
            / "book_ranks_summary.json"
        )
    env = os.environ.get("EARNINGS_MONITOR_HISTORY_SOURCE")
    if env:
        root = Path(env)
        candidates.append(root / "cross_company" / "json" / "book_ranks_summary.json")
    for path in candidates:
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                return payload
    return None
