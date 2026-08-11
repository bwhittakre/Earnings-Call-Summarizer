"""Pure data access and transformation helpers for the monitor dashboard."""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from ..ops_health import (
    book_ranks_summary_alerts,
    event_is_stuck,
    host_health_alerts,
    load_book_ranks_summary,
    load_host_health,
    research_freshness_alerts,
    resolve_host_health_path,
)
from ..storage import read_company_quarter_dataset, record_to_dict


_PERIOD_RE = re.compile(r"^FY(\d{4})-Q([1-4])$", re.IGNORECASE)
_CALENDAR_RE = re.compile(r"^(\d{4})-Q([1-4])$", re.IGNORECASE)

# Company-level "Flagged" attention excludes routine sparse_dimension marks.
# Those mean a composite dimension used fewer member measures — still usable.
_SEVERE_QUALITY_FLAGS = frozenset(
    {
        "near_zero_consensus",
        "member_suppressed",
    }
)


def _period_key(value: Any) -> tuple[int, int, str]:
    text = str(value or "")
    match = _PERIOD_RE.match(text)
    if match:
        return (int(match.group(1)), int(match.group(2)), text)
    cal = _CALENDAR_RE.match(text)
    if cal:
        return (int(cal.group(1)), int(cal.group(2)), text)
    return (-1, -1, text)


def _number(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _mean(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    values = [value for row in rows if (value := _number(row.get(key))) is not None]
    return round(fmean(values), 4) if values else None


def _decode_json(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(str(value))
    except (TypeError, ValueError):
        return default


def _quality_flags(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    flags: set[str] = set()
    for row in rows:
        raw = row.get("quant_quality_flags")
        parsed = _decode_json(raw, [])
        if isinstance(parsed, list):
            flags.update(str(flag) for flag in parsed if flag)
        elif raw not in (None, ""):
            flags.update(
                part.strip() for part in str(raw).split("|") if part.strip()
            )
    return sorted(flags)


def _quality_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    flags = _quality_flags(rows)
    severe = [flag for flag in flags if flag in _SEVERE_QUALITY_FLAGS]
    if not rows:
        return {
            "quant_quality_ok": True,
            "quant_quality_flags": [],
            "quant_flagged": False,
            "quant_severe_flags": [],
        }
    # Decision-grade OK / pulse Flagged ignore routine sparse_dimension marks.
    return {
        "quant_quality_ok": not severe,
        "quant_quality_flags": flags,
        "quant_severe_flags": severe,
        "quant_flagged": bool(severe),
    }


@dataclass
class DashboardData:
    """A stable dashboard facade over loose record dictionaries."""

    rows: list[dict[str, Any]]
    operational_events: list[dict[str, Any]] = field(default_factory=list)
    job_runs: list[dict[str, Any]] = field(default_factory=list)
    poll_cycles: list[dict[str, Any]] = field(default_factory=list)
    artifact_publications: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_records(
        cls,
        records: Iterable[Any],
        *,
        operational_events: Iterable[Any] = (),
        job_runs: Iterable[Any] = (),
        poll_cycles: Iterable[Any] = (),
        artifact_publications: Iterable[Any] = (),
    ) -> "DashboardData":
        return cls(
            [record_to_dict(record) for record in records],
            [record_to_dict(event) for event in operational_events],
            [record_to_dict(run) for run in job_runs],
            [record_to_dict(cycle) for cycle in poll_cycles],
            [record_to_dict(publication) for publication in artifact_publications],
        )

    @property
    def tickers(self) -> list[str]:
        return sorted({str(row.get("ticker", "")).upper() for row in self.rows if row.get("ticker")})

    def _group_quarters(
        self,
        *,
        ticker: str | None = None,
    ) -> dict[tuple[str, str], list[dict[str, Any]]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        ticker_filter = ticker.upper() if ticker else None
        for row in self.rows:
            row_ticker = str(row.get("ticker", "")).upper()
            period = str(row.get("fiscal_period", ""))
            if not row_ticker or not period or (ticker_filter and row_ticker != ticker_filter):
                continue
            grouped.setdefault((row_ticker, period), []).append(row)
        return grouped

    def event_inbox(
        self, *, limit: int = 100, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        if self.operational_events:
            current = now or datetime.now(timezone.utc)
            stuck_after = int(os.environ.get("EARNINGS_MONITOR_STUCK_EVENT_SECONDS", "7200"))
            failures = self._repeated_failure_counts()
            events = [
                {
                    "ticker": str(row.get("ticker", "")).upper(),
                    "fiscal_period": row.get("fiscal_period"),
                    "report_at": row.get("report_at"),
                    "call_at": row.get("call_at", row.get("scheduled_at")),
                    "status": row.get("state"),
                    "workflow_mode": (
                        row.get("workflow_mode")
                        or (
                            "first_print"
                            if row.get("first_print") in (1, True, "1")
                            else "standard"
                        )
                    ),
                    "first_print": bool(row.get("first_print")),
                    "last_error": row.get("last_error"),
                    "source_url": row.get("source_url"),
                    "updated_at": row.get("updated_at"),
                    "stuck": event_is_stuck(
                        row, now=current, stuck_after_seconds=stuck_after
                    )[0],
                    "age_seconds": self._age_seconds(row.get("updated_at"), current),
                    "failed_runs": failures[str(row.get("provider_event_id"))],
                }
                for row in self.operational_events
            ]
            events.sort(
                key=lambda row: (
                    str(row.get("call_at") or ""),
                    str(row.get("ticker") or ""),
                ),
                reverse=True,
            )
            return events[:limit]
        events: list[dict[str, Any]] = []
        for (ticker, period), rows in self._group_quarters().items():
            first = rows[0]
            divergence_count = sum(
                _truthy(row.get("any_quant_divergence", row.get("is_divergence")))
                for row in rows
            )
            events.append(
                {
                    "ticker": ticker,
                    "fiscal_period": period,
                    "earnings_date": first.get("earnings_date", first.get("as_of_date")),
                    "status": "incomplete"
                    if any(_truthy(row.get("history_incomplete")) for row in rows)
                    else "ready",
                    "dimensions": sum(row.get("dimension") not in (None, "") for row in rows),
                    "divergences": divergence_count,
                    "mean_narrative_level": _mean(rows, "llm_level"),
                    "mean_quant_z": _mean(rows, "quant_z_pit")
                    if any(row.get("quant_z_pit") not in (None, "") for row in rows)
                    else _mean(rows, "quant_z"),
                }
            )
        events.sort(
            key=lambda row: (
                str(row.get("earnings_date") or ""),
                _period_key(row["fiscal_period"]),
                row["ticker"],
            ),
            reverse=True,
        )
        return events[:limit]

    @staticmethod
    def _age_seconds(value: Any, now: datetime) -> int:
        if not value:
            return 0
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0, int((now - parsed.astimezone(timezone.utc)).total_seconds()))
        except (TypeError, ValueError):
            return 0

    def run_timeline(
        self, provider_event_id: str | None = None
    ) -> list[dict[str, Any]]:
        runs = self.job_runs
        if provider_event_id:
            runs = [
                run
                for run in runs
                if str(run.get("provider_event_id")) == provider_event_id
            ]
        timeline = [
            {
                "provider_event_id": run.get("provider_event_id"),
                "stage": run.get("stage"),
                "attempt": run.get("attempt"),
                "status": run.get("status"),
                "started_at": run.get("started_at"),
                "finished_at": run.get("finished_at"),
                "duration_ms": run.get("duration_ms"),
                "result": _decode_json(run.get("result_json"), {}),
                "error": run.get("error_summary"),
            }
            for run in runs
        ]
        timeline.sort(key=lambda row: str(row.get("started_at") or ""), reverse=True)
        return timeline

    def _repeated_failure_counts(self) -> Counter[str]:
        return self._repeated_failure_episodes()[0]

    def _repeated_failure_episodes(self) -> tuple[Counter[str], dict[str, str]]:
        by_event: dict[str, list[dict[str, Any]]] = {}
        for run in self.job_runs:
            by_event.setdefault(str(run.get("provider_event_id")), []).append(run)
        counts: Counter[str] = Counter()
        anchors: dict[str, str] = {}
        for event_id, runs in by_event.items():
            runs.sort(key=lambda run: str(run.get("started_at") or ""), reverse=True)
            for run in runs:
                if run.get("status") != "failed":
                    break
                counts[event_id] += 1
                # The oldest failure in the current consecutive streak anchors
                # one incident. A successful run ends it, allowing a later
                # failure streak to generate a distinct notification.
                anchors[event_id] = str(
                    run.get("started_at") or run.get("id") or "unknown"
                )
        return counts, anchors

    def operational_alerts(
        self,
        *,
        now: datetime | None = None,
        stuck_after_seconds: int | None = None,
        repeated_failure_threshold: int | None = None,
    ) -> list[dict[str, Any]]:
        current = now or datetime.now(timezone.utc)
        stuck_after = stuck_after_seconds or int(
            os.environ.get("EARNINGS_MONITOR_STUCK_EVENT_SECONDS", "7200")
        )
        failure_threshold = repeated_failure_threshold or int(
            os.environ.get("EARNINGS_MONITOR_REPEATED_FAILURE_THRESHOLD", "2")
        )
        alerts: list[dict[str, Any]] = []
        failed, failure_episodes = self._repeated_failure_episodes()
        for event in self.operational_events:
            event_id = str(event.get("provider_event_id"))
            state = str(event.get("state") or "unknown")
            age = self._age_seconds(event.get("updated_at"), current)
            stuck, stuck_detail = event_is_stuck(
                event, now=current, stuck_after_seconds=stuck_after
            )
            if stuck:
                alerts.append(
                    {
                        "kind": "stuck_event",
                        "severity": "warning",
                        "provider_event_id": event_id,
                        "ticker": event.get("ticker"),
                        "state": state,
                        "age_seconds": age,
                        "occurrence": event.get("updated_at"),
                        "detail": stuck_detail
                        or f"event unchanged for {age} seconds",
                    }
                )
            if failed[event_id] >= failure_threshold:
                alerts.append(
                    {
                        "kind": "repeated_failure",
                        "severity": "error",
                        "provider_event_id": event_id,
                        "ticker": event.get("ticker"),
                        "state": state,
                        "failures": failed[event_id],
                        "occurrence": failure_episodes.get(event_id),
                        "detail": f"{failed[event_id]} failed workflow attempts",
                    }
                )
        if self.poll_cycles:
            latest = max(
                self.poll_cycles, key=lambda cycle: str(cycle.get("started_at") or "")
            )
            poll_seconds = int(os.environ.get("EARNINGS_MONITOR_POLL_SECONDS", "300"))
            age = self._age_seconds(latest.get("finished_at") or latest.get("started_at"), current)
            if age >= max(poll_seconds * 2, 600):
                alerts.append(
                    {
                        "kind": "stale_poller",
                        "severity": "error",
                        "occurrence": latest.get("id") or latest.get("started_at"),
                        "age_seconds": age,
                        "detail": f"no completed poll cycle for {age} seconds",
                    }
                )
        for publication in self.artifact_publications:
            if publication.get("status") == "failed":
                alerts.append(
                    {
                        "kind": "artifact_publish_failed",
                        "severity": "error",
                        "provider_event_id": publication.get("provider_event_id"),
                        "occurrence": (
                            publication.get("publication_key")
                            or publication.get("id")
                        ),
                        "failures": publication.get("attempts"),
                        "detail": publication.get("last_error"),
                    }
                )

        health = load_host_health(resolve_host_health_path())
        alerts.extend(host_health_alerts(health, now=current))

        try:
            from .research_data import (
                artifact_universe_status,
                format_universe_stale_message,
                load_consolidated_panel,
                load_rank_ic_bundle,
                load_research_book_dirty,
            )

            dirty = load_research_book_dirty()
            last_regen = None
            try:
                from ..state import OperationalState

                db = default_operational_db_path()
                if db.is_file():
                    state = OperationalState(db)
                    state.initialize()
                    raw = state.get_meta("research_book_last_regen")
                    if raw:
                        last_regen = json.loads(raw)
            except Exception:  # noqa: BLE001
                last_regen = None
            rank_ic = load_rank_ic_bundle()
            consolidated = load_consolidated_panel()
            universe_status = artifact_universe_status(
                self.tickers,
                rank_ic.meta if rank_ic.available else None,
                consolidated.meta if consolidated.available else None,
            )
            universe_msg = format_universe_stale_message(universe_status)
            alerts.extend(
                research_freshness_alerts(
                    dirty=dirty,
                    last_regen=last_regen if isinstance(last_regen, dict) else None,
                    now=current,
                    debounce_seconds=int(
                        os.environ.get("EARNINGS_MONITOR_RESEARCH_REGEN_DEBOUNCE", "60")
                    ),
                    idle_seconds=int(
                        os.environ.get("EARNINGS_MONITOR_RESEARCH_REGEN_IDLE", "30")
                    ),
                    universe_stale_message=universe_msg,
                )
            )
        except Exception:  # noqa: BLE001
            pass

        ranks_summary = load_book_ranks_summary() or {}
        try:
            from ..state import OperationalState

            db = default_operational_db_path()
            if db.is_file():
                state = OperationalState(db)
                state.initialize()
                raw_err = state.get_meta("book_ranks_last_error")
                if raw_err:
                    err_payload = json.loads(raw_err)
                    if isinstance(err_payload, dict) and err_payload.get("ok") is False:
                        ranks_summary = {
                            **ranks_summary,
                            "ok": False,
                            "last_error": err_payload.get("error"),
                            "built_at": err_payload.get("at")
                            or ranks_summary.get("built_at"),
                        }
        except Exception:  # noqa: BLE001
            pass
        alerts.extend(
            book_ranks_summary_alerts(ranks_summary or None, now=current)
        )

        # Deduplicate identical kind+occurrence rows.
        seen: set[tuple[Any, ...]] = set()
        unique: list[dict[str, Any]] = []
        for alert in alerts:
            key = (
                alert.get("kind"),
                alert.get("provider_event_id"),
                alert.get("occurrence"),
                alert.get("detail"),
            )
            if key in seen:
                continue
            seen.add(key)
            unique.append(alert)
        return unique

    def host_feed_status(self, *, now: datetime | None = None) -> dict[str, Any]:
        """Summary strip for Operations: last host run + open failures."""
        current = now or datetime.now(timezone.utc)
        health_path = resolve_host_health_path()
        health = load_host_health(health_path)
        due_sweep = Path("host_quartr/worklists/due_sweep.json")
        env_root = os.environ.get("EARNINGS_MONITOR_REPO_ROOT")
        if env_root:
            due_sweep = Path(env_root) / "host_quartr" / "worklists" / "due_sweep.json"
        due_mtime = None
        if due_sweep.is_file():
            due_mtime = datetime.fromtimestamp(
                due_sweep.stat().st_mtime, tz=timezone.utc
            ).isoformat()
        if not health:
            return {
                "available": False,
                "path": str(health_path) if health_path else None,
                "due_sweep_mtime": due_mtime,
                "failures": [],
            }
        finished = health.get("finished_at") or health.get("started_at")
        return {
            "available": True,
            "path": str(health_path) if health_path else None,
            "job": health.get("job"),
            "ok": health.get("ok"),
            "finished_at": finished,
            "age_seconds": self._age_seconds(finished, current),
            "counts": health.get("counts") or {},
            "failures": health.get("failures") or [],
            "due_sweep_mtime": due_mtime,
        }

    def company_history(self, ticker: str) -> list[dict[str, Any]]:
        history: list[dict[str, Any]] = []
        for (_, period), rows in self._group_quarters(ticker=ticker).items():
            first = rows[0]
            quality = _quality_summary(rows)
            history.append(
                {
                    "fiscal_period": period,
                    "period_end_date": first.get("period_end_date"),
                    "earnings_date": first.get("earnings_date", first.get("as_of_date")),
                    "dimensions": sum(row.get("dimension") not in (None, "") for row in rows),
                    "narrative_level": _mean(rows, "llm_level"),
                    "narrative_change": _mean(rows, "change_magnitude"),
                    "quant_z": _mean(rows, "quant_z_pit")
                    if any(row.get("quant_z_pit") not in (None, "") for row in rows)
                    else _mean(rows, "quant_z"),
                    "narrative_quant_gap": _mean(rows, "narrative_quant_gap"),
                    "divergences": sum(
                        _truthy(
                            row.get(
                                "any_quant_divergence",
                                row.get("is_divergence"),
                            )
                        )
                        for row in rows
                    ),
                    "incomplete": any(_truthy(row.get("history_incomplete")) for row in rows),
                    "quant_quality_ok": quality["quant_quality_ok"],
                    "quant_quality_flags": quality["quant_quality_flags"],
                    "quant_flagged": quality["quant_flagged"],
                }
            )
        history.sort(key=lambda row: _period_key(row["fiscal_period"]))
        return history

    def latest_scorecards(self) -> list[dict[str, Any]]:
        grouped = self._group_quarters()
        scorecards: list[dict[str, Any]] = []
        for ticker in self.tickers:
            periods = sorted(
                (period for row_ticker, period in grouped if row_ticker == ticker),
                key=_period_key,
            )
            if not periods:
                continue
            period = periods[-1]
            rows = grouped[(ticker, period)]
            quality = _quality_summary(rows)
            scorecards.append(
                {
                    "ticker": ticker,
                    "fiscal_period": period,
                    "dimensions": sum(
                        row.get("dimension") not in (None, "") for row in rows
                    ),
                    "narrative_level": _mean(rows, "llm_level"),
                    "narrative_change": _mean(rows, "change_magnitude"),
                    "narrative_surprise": _mean(rows, "surprise_magnitude"),
                    "quant_z": _mean(rows, "quant_z_pit")
                    if any(row.get("quant_z_pit") not in (None, "") for row in rows)
                    else _mean(rows, "quant_z"),
                    "narrative_quant_gap": _mean(rows, "narrative_quant_gap"),
                    "divergences": sum(
                        _truthy(
                            row.get(
                                "any_quant_divergence",
                                row.get("is_divergence"),
                            )
                        )
                        for row in rows
                    ),
                    "incomplete": any(
                        _truthy(row.get("history_incomplete")) for row in rows
                    ),
                    "quant_quality_ok": quality["quant_quality_ok"],
                    "quant_quality_flags": quality["quant_quality_flags"],
                    "quant_flagged": quality["quant_flagged"],
                }
            )
        return scorecards

    def completeness_coverage(self) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for ticker in self.tickers:
            history = self.company_history(ticker)
            incomplete = sum(_truthy(row.get("incomplete")) for row in history)
            total = len(history)
            output.append(
                {
                    "ticker": ticker,
                    "quarters": total,
                    "complete": total - incomplete,
                    "incomplete": incomplete,
                    "coverage_pct": round(
                        100 * (total - incomplete) / total, 1
                    )
                    if total
                    else 0.0,
                }
            )
        return output

    def pipeline_status(self) -> list[dict[str, Any]]:
        counts = Counter(
            str(event.get("state") or "unknown") for event in self.operational_events
        )
        return [
            {"status": status, "events": count}
            for status, count in sorted(counts.items())
        ]

    def overview(self) -> dict[str, Any]:
        quarter_count = len(self._group_quarters())
        incomplete = sum(row["incomplete"] for row in self.completeness_coverage())
        active_states = {
            "scheduled",
            "onboarding",
            "onboarding_blocked",
            "baseline_queued",
            "baseline_running",
            "awaiting_release",
            "awaiting_quant_data",
            "quant_queued",
            "quant_running",
            "awaiting_call",
            "transcript_pending",
            "transcript_unstable",
            "post_call_queued",
            "post_call_running",
        }
        active_events = sum(
            str(event.get("state") or "") in active_states
            for event in self.operational_events
        )
        return {
            "companies": len(self.tickers),
            "history_rows": len(self.rows),
            "quarters": quarter_count,
            "incomplete_quarters": incomplete,
            "armed_events": len(self.operational_events),
            "active_events": active_events,
        }

    def dimension_heatmap(
        self,
        *,
        tickers: Sequence[str] | None = None,
        latest_periods: int = 8,
    ) -> list[dict[str, Any]]:
        """Period × dimension cells for selected tickers.

        Uses a shared period-end **calendar-quarter** window (same convention as
        Consolidated / Rank IC) so companies with different fiscal calendars
        align on the x-axis.
        """
        allowed = {ticker.upper() for ticker in tickers} if tickers else set(self.tickers)

        calendar_quarters = sorted(
            {
                str(row.get("period_end_calendar_quarter") or "")
                for row in self.rows
                if str(row.get("ticker") or "").upper() in allowed
                and row.get("period_end_calendar_quarter") not in (None, "")
            },
            key=_period_key,
        )
        use_calendar = bool(calendar_quarters)
        if use_calendar:
            selected_window = set(calendar_quarters[-latest_periods:])
        else:
            # Fiscal fallback when calendar enrichment is missing.
            grouped = self._group_quarters()
            selected_periods: dict[str, set[str]] = {}
            for ticker in allowed:
                periods = sorted(
                    (period for row_ticker, period in grouped if row_ticker == ticker),
                    key=_period_key,
                )
                selected_periods[ticker] = set(periods[-latest_periods:])

        cells: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        for row in self.rows:
            ticker = str(row.get("ticker") or "").upper()
            fiscal = str(row.get("fiscal_period") or "")
            calendar = str(row.get("period_end_calendar_quarter") or "")
            dimension = str(row.get("dimension") or "")
            if ticker not in allowed or not dimension:
                continue
            if use_calendar:
                if calendar not in selected_window:
                    continue
            else:
                if fiscal not in selected_periods.get(ticker, set()):
                    continue
            key = (ticker, calendar or fiscal, fiscal, dimension)
            cells.setdefault(key, []).append(row)

        output: list[dict[str, Any]] = []
        for (ticker, calendar, fiscal, dimension), rows in cells.items():
            output.append(
                {
                    "ticker": ticker,
                    "calendar_quarter": calendar or None,
                    "fiscal_period": fiscal,
                    # Chart x-axis: prefer calendar quarter for cross-company alignment.
                    "period": calendar or fiscal,
                    "dimension": dimension,
                    "narrative_level": _mean(rows, "llm_level"),
                    "quant_z": _mean(rows, "quant_z_pit")
                    if any(row.get("quant_z_pit") not in (None, "") for row in rows)
                    else _mean(rows, "quant_z"),
                    "gap": _mean(rows, "narrative_quant_gap"),
                    "divergence": any(
                        _truthy(
                            row.get(
                                "any_quant_divergence",
                                row.get("is_divergence"),
                            )
                        )
                        for row in rows
                    ),
                }
            )
        output.sort(
            key=lambda row: (
                row["ticker"],
                _period_key(row.get("period") or row["fiscal_period"]),
                row["dimension"],
            )
        )
        return output

    def cross_company(
        self,
        *,
        latest_periods: int = 12,
        dimension: str | None = None,
    ) -> list[dict[str, Any]]:
        """Universe ranking rows for the cross-company board.

        When *dimension* is None, aggregates quarter-level company history.
        When set, aggregates that dimension's cells over the trailing window.
        """
        if dimension:
            return self._cross_company_by_dimension(
                latest_periods=latest_periods,
                dimension=dimension,
            )

        summary: list[dict[str, Any]] = []
        for ticker in self.tickers:
            history = self.company_history(ticker)
            selected = history[-latest_periods:] if latest_periods > 0 else history
            dim_counts = [
                int(row["dimensions"])
                for row in selected
                if isinstance(row.get("dimensions"), (int, float))
            ]
            div_counts = [
                int(row["divergences"])
                for row in selected
                if isinstance(row.get("divergences"), (int, float))
            ]
            total_dims = sum(dim_counts)
            total_divs = sum(div_counts)
            summary.append(
                {
                    "ticker": ticker,
                    "quarters": len(selected),
                    "latest_period": history[-1]["fiscal_period"] if history else None,
                    "scope": "all_dimensions",
                    "mean_narrative_level": _mean(selected, "narrative_level"),
                    "mean_narrative_change": _mean(selected, "narrative_change"),
                    "mean_quant_z": _mean(selected, "quant_z"),
                    "mean_narrative_quant_gap": _mean(selected, "narrative_quant_gap"),
                    "divergence_rate": round(total_divs / total_dims, 4)
                    if total_dims
                    else None,
                    "incomplete_quarters": sum(
                        _truthy(row.get("incomplete")) for row in history
                    ),
                }
            )
        return summary

    def _cross_company_by_dimension(
        self,
        *,
        latest_periods: int,
        dimension: str,
    ) -> list[dict[str, Any]]:
        cells = self.dimension_heatmap(
            tickers=self.tickers,
            latest_periods=latest_periods,
        )
        by_ticker: dict[str, list[dict[str, Any]]] = {}
        for row in cells:
            if str(row.get("dimension")) != dimension:
                continue
            by_ticker.setdefault(str(row["ticker"]).upper(), []).append(row)

        summary: list[dict[str, Any]] = []
        for ticker in self.tickers:
            selected = by_ticker.get(ticker, [])
            if not selected:
                history = self.company_history(ticker)
                summary.append(
                    {
                        "ticker": ticker,
                        "quarters": 0,
                        "latest_period": history[-1]["fiscal_period"]
                        if history
                        else None,
                        "scope": dimension,
                        "mean_narrative_level": None,
                        "mean_narrative_change": None,
                        "mean_quant_z": None,
                        "mean_narrative_quant_gap": None,
                        "divergence_rate": None,
                        "incomplete_quarters": sum(
                            _truthy(row.get("incomplete")) for row in history
                        ),
                    }
                )
                continue
            periods = sorted(
                {str(row["fiscal_period"]) for row in selected},
                key=_period_key,
            )
            divs = sum(_truthy(row.get("divergence")) for row in selected)
            summary.append(
                {
                    "ticker": ticker,
                    "quarters": len(periods),
                    "latest_period": periods[-1] if periods else None,
                    "scope": dimension,
                    "mean_narrative_level": _mean(selected, "narrative_level"),
                    "mean_narrative_change": None,
                    "mean_quant_z": _mean(selected, "quant_z"),
                    "mean_narrative_quant_gap": _mean(selected, "gap"),
                    "divergence_rate": round(divs / len(selected), 4)
                    if selected
                    else None,
                    "incomplete_quarters": sum(
                        _truthy(row.get("incomplete"))
                        for row in self.company_history(ticker)
                    ),
                }
            )
        return summary

    def overview_pulse(self) -> list[dict[str, Any]]:
        """Latest-print attention rows sorted by absolute surprise–quant gap."""
        pulse: list[dict[str, Any]] = []
        for row in self.latest_scorecards():
            gap = _number(row.get("narrative_quant_gap"))
            pulse.append(
                {
                    "ticker": row["ticker"],
                    "fiscal_period": row["fiscal_period"],
                    "gap": gap,
                    "abs_gap": abs(gap) if gap is not None else None,
                    "narrative_level": row.get("narrative_level"),
                    "narrative_surprise": row.get("narrative_surprise"),
                    "quant_z": row.get("quant_z"),
                    "quant_flagged": bool(row.get("quant_flagged")),
                    "incomplete": bool(row.get("incomplete")),
                }
            )
        pulse.sort(
            key=lambda item: (
                item["abs_gap"] is None,
                -(item["abs_gap"] or 0.0),
                item["ticker"],
            )
        )
        return pulse

    def narrative_vs_quant(
        self,
        *,
        tickers: Sequence[str] | None = None,
        dimension: str | None = None,
        peer_tickers: Sequence[str] | None = None,
        enrich: bool = True,
    ) -> list[dict[str, Any]]:
        from .nvq_analytics import (
            compute_agreement_streaks,
            compute_peer_gap_deltas,
        )

        allowed = {ticker.upper() for ticker in tickers} if tickers else None
        points: list[dict[str, Any]] = []
        for row in self.rows:
            ticker = str(row.get("ticker", "")).upper()
            if allowed is not None and ticker not in allowed:
                continue
            if dimension and str(row.get("dimension", "")) != dimension:
                continue
            narrative = _number(row.get("llm_level"))
            quant = _number(row.get("quant_z_pit"))
            if quant is None:
                quant = _number(row.get("quant_z"))
            if narrative is None or quant is None:
                continue
            gap = _number(row.get("narrative_quant_gap"))
            if gap is None:
                gap = narrative - quant
            calendar = row.get("period_end_calendar_quarter")
            calendar_text = str(calendar) if calendar not in (None, "") else ""
            fiscal = row.get("fiscal_period")
            divergence = _truthy(
                row.get("any_quant_divergence", row.get("is_divergence"))
            )
            points.append(
                {
                    "ticker": ticker,
                    "fiscal_period": fiscal,
                    "calendar_quarter": calendar_text or str(fiscal or ""),
                    "calendar_quarter_fallback": not bool(calendar_text),
                    "dimension": row.get("dimension"),
                    "narrative_level": narrative,
                    "quant_z": quant,
                    "gap": gap,
                    "divergence": divergence,
                    "agreement": "Divergence" if divergence else "Aligned",
                }
            )
        if not enrich:
            return points

        points = compute_agreement_streaks(points)
        peer_universe = points
        if peer_tickers is not None:
            peer_universe = self.narrative_vs_quant(
                tickers=peer_tickers,
                dimension=dimension,
                enrich=False,
            )
            # Streaks not required for peer medians; gaps/calendar are enough.
        return compute_peer_gap_deltas(points, peer_universe)

    def audit(self, *, incomplete_only: bool = False) -> list[dict[str, Any]]:
        audits: list[dict[str, Any]] = []
        for (ticker, period), rows in self._group_quarters().items():
            first = rows[0]
            incomplete = any(_truthy(row.get("history_incomplete")) for row in rows)
            if incomplete_only and not incomplete:
                continue
            flags: set[str] = set()
            for row in rows:
                decoded = _decode_json(row.get("history_incomplete_flags"), [])
                if isinstance(decoded, list):
                    flags.update(str(item) for item in decoded)
            provenance = _decode_json(first.get("history_provenance"), {})
            panel = provenance.get("panel") or {} if isinstance(provenance, dict) else {}
            registry = provenance.get("registry") or {} if isinstance(provenance, dict) else {}
            audits.append(
                {
                    "ticker": ticker,
                    "fiscal_period": period,
                    "incomplete": incomplete,
                    "flags": ", ".join(sorted(flags)),
                    "panel_source": panel.get("path", first.get("source_path")),
                    "panel_sha256": panel.get("sha256", first.get("source_sha256")),
                    "registry_source": registry.get("path"),
                    "imported_at": first.get("history_imported_at"),
                }
            )
        audits.sort(key=lambda row: (row["ticker"], _period_key(row["fiscal_period"])))
        return audits

    @property
    def dimensions(self) -> list[str]:
        return sorted(
            {str(row["dimension"]) for row in self.rows if row.get("dimension") not in (None, "")}
        )


def default_dataset_path() -> Path:
    configured = os.environ.get("EARNINGS_MONITOR_DATASET")
    if configured:
        return Path(configured).expanduser()
    return Path("data/earnings_monitor/company_quarters.parquet")


def default_operational_db_path() -> Path:
    configured = os.environ.get("EARNINGS_MONITOR_DB")
    if configured:
        return Path(configured).expanduser()
    return Path("services/earnings_monitor/state/monitor.sqlite3")


def load_operational_events(path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    database = Path(path or default_operational_db_path())
    if not database.is_file():
        return []
    try:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            # Prefer workflow_mode / first_print when migrated; fall back if absent.
            try:
                rows = connection.execute(
                    """
                    SELECT provider_event_id, ticker, fiscal_period, report_at, call_at,
                           scheduled_at, source_url, state, last_error, updated_at,
                           workflow_mode, first_print
                    FROM events
                    ORDER BY call_at DESC
                    """
                ).fetchall()
            except sqlite3.Error:
                rows = connection.execute(
                    """
                    SELECT provider_event_id, ticker, fiscal_period, report_at, call_at,
                           scheduled_at, source_url, state, last_error, updated_at
                    FROM events
                    ORDER BY call_at DESC
                    """
                ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def load_operational_history(
    path: str | os.PathLike[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    database = Path(path or default_operational_db_path())
    empty = {"job_runs": [], "poll_cycles": [], "artifact_publications": []}
    if not database.is_file():
        return empty
    try:
        connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            result: dict[str, list[dict[str, Any]]] = {}
            for table, order in (
                ("job_runs", "started_at DESC"),
                ("poll_cycles", "started_at DESC"),
                ("artifact_publications", "available_at DESC"),
            ):
                try:
                    rows = connection.execute(
                        f"SELECT * FROM {table} ORDER BY {order} LIMIT 500"
                    ).fetchall()
                except sqlite3.Error:
                    rows = []
                result[table] = [dict(row) for row in rows]
            return result
        finally:
            connection.close()
    except sqlite3.Error:
        return empty


def load_dashboard_data(
    path: str | os.PathLike[str] | None = None,
    *,
    operational_db_path: str | os.PathLike[str] | None = None,
) -> DashboardData:
    history = load_operational_history(operational_db_path)
    return DashboardData.from_records(
        read_company_quarter_dataset(path or default_dataset_path()),
        operational_events=load_operational_events(operational_db_path),
        job_runs=history["job_runs"],
        poll_cycles=history["poll_cycles"],
        artifact_publications=history["artifact_publications"],
    )
