"""SQLite-backed operational state with atomic job claiming."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from .models import EarningsEvent, EventState, JobStatus, MonitoredEvent


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class OperationalState:
    def __init__(
        self,
        path: Path | str,
        *,
        lease_timeout: timedelta = timedelta(hours=1),
    ):
        self.path = Path(path)
        if lease_timeout <= timedelta(0):
            raise ValueError("lease_timeout must be positive")
        self.lease_timeout = lease_timeout

    def initialize(self, *, now: datetime | None = None) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode=WAL;
                PRAGMA foreign_keys=ON;
                CREATE TABLE IF NOT EXISTS events (
                    provider_event_id TEXT PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    fiscal_period TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL,
                    report_at TEXT,
                    call_at TEXT,
                    title TEXT NOT NULL DEFAULT '',
                    source_url TEXT,
                    state TEXT NOT NULL,
                    transcript_fingerprint TEXT,
                    transcript_observed_at TEXT,
                    last_error TEXT,
                    updated_at TEXT NOT NULL,
                    manual_override INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(ticker, fiscal_period)
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    provider_event_id TEXT NOT NULL REFERENCES events(provider_event_id),
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    available_at TEXT NOT NULL,
                    claimed_at TEXT,
                    finished_at TEXT,
                    last_error TEXT
                );
                CREATE INDEX IF NOT EXISTS jobs_ready
                    ON jobs(status, available_at, id);
                CREATE TABLE IF NOT EXISTS notifications (
                    notification_key TEXT PRIMARY KEY,
                    sent_at TEXT,
                    status TEXT NOT NULL DEFAULT 'sent',
                    claimed_at TEXT
                );
                CREATE TABLE IF NOT EXISTS poll_cycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error_summary TEXT
                );
                CREATE INDEX IF NOT EXISTS poll_cycles_started
                    ON poll_cycles(started_at DESC);
                CREATE TABLE IF NOT EXISTS job_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id INTEGER NOT NULL REFERENCES jobs(id),
                    provider_event_id TEXT NOT NULL REFERENCES events(provider_event_id),
                    stage TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    duration_ms INTEGER,
                    status TEXT NOT NULL,
                    result_json TEXT,
                    error_summary TEXT
                );
                CREATE INDEX IF NOT EXISTS job_runs_event
                    ON job_runs(provider_event_id, started_at DESC);
                CREATE TABLE IF NOT EXISTS artifact_publications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    publication_key TEXT NOT NULL UNIQUE,
                    provider_event_id TEXT NOT NULL REFERENCES events(provider_event_id),
                    fingerprint TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    available_at TEXT NOT NULL,
                    claimed_at TEXT,
                    completed_at TEXT,
                    manifest_uri TEXT,
                    last_error TEXT
                );
                CREATE INDEX IF NOT EXISTS artifact_publications_ready
                    ON artifact_publications(status, available_at, id);
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
            if "report_at" not in columns:
                conn.execute("ALTER TABLE events ADD COLUMN report_at TEXT")
            if "call_at" not in columns:
                conn.execute("ALTER TABLE events ADD COLUMN call_at TEXT")
            if "manual_override" not in columns:
                conn.execute(
                    "ALTER TABLE events ADD COLUMN manual_override "
                    "INTEGER NOT NULL DEFAULT 0"
                )
                # Before watched discovery existed, every persisted schedule
                # was operator/local supplied. Preserve those schedules across
                # the migration instead of guessing from the event ID format.
                conn.execute(
                    "UPDATE events SET manual_override=1"
                )
            conn.execute(
                "UPDATE events SET report_at=COALESCE(report_at, scheduled_at), "
                "call_at=COALESCE(call_at, scheduled_at)"
            )
            conn.execute(
                """
                UPDATE events SET state=CASE
                    WHEN state='succeeded' THEN 'complete'
                    WHEN state IN (
                        'call_started', 'ready', 'queued', 'running'
                    ) THEN 'scheduled'
                    ELSE state
                END
                """
            )
            notification_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(notifications)")
            }
            if "status" not in notification_columns:
                conn.execute(
                    "ALTER TABLE notifications ADD COLUMN status TEXT "
                    "NOT NULL DEFAULT 'sent'"
                )
            if "claimed_at" not in notification_columns:
                conn.execute("ALTER TABLE notifications ADD COLUMN claimed_at TEXT")
        self.recover_stale_leases(now=now)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
        finally:
            conn.close()

    def upsert_event(self, monitored: MonitoredEvent) -> None:
        event = monitored.event
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (
                    provider_event_id, ticker, fiscal_period, scheduled_at, report_at, call_at, title,
                    source_url, state, transcript_fingerprint, transcript_observed_at,
                    last_error, updated_at, manual_override
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_event_id) DO UPDATE SET
                    ticker=excluded.ticker, fiscal_period=excluded.fiscal_period,
                    scheduled_at=excluded.scheduled_at, report_at=excluded.report_at,
                    call_at=excluded.call_at, title=excluded.title,
                    source_url=excluded.source_url, state=excluded.state,
                    transcript_fingerprint=excluded.transcript_fingerprint,
                    transcript_observed_at=excluded.transcript_observed_at,
                    last_error=excluded.last_error, updated_at=excluded.updated_at,
                    manual_override=excluded.manual_override
                """,
                (
                    event.provider_event_id,
                    event.ticker,
                    event.fiscal_period,
                    _iso(event.call_at),
                    _iso(event.report_at),
                    _iso(event.call_at),
                    event.title,
                    event.source_url,
                    monitored.state.value,
                    monitored.transcript_fingerprint,
                    _iso(monitored.transcript_observed_at),
                    monitored.last_error,
                    _iso(monitored.updated_at),
                    int(monitored.manual_override),
                ),
            )

    def arm_event(self, event: EarningsEvent) -> MonitoredEvent:
        """Apply a manual schedule while retaining any existing period identity/lifecycle."""
        now = datetime.now(timezone.utc)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM events WHERE ticker=? AND fiscal_period=?",
                (event.ticker, event.fiscal_period),
            ).fetchone()
            if row is None:
                row = conn.execute(
                    "SELECT * FROM events WHERE provider_event_id=?",
                    (event.provider_event_id,),
                ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO events(
                        provider_event_id, ticker, fiscal_period, scheduled_at,
                        report_at, call_at, title, source_url, state, updated_at,
                        manual_override
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        event.provider_event_id,
                        event.ticker,
                        event.fiscal_period,
                        _iso(event.call_at),
                        _iso(event.report_at),
                        _iso(event.call_at),
                        event.title,
                        event.source_url,
                        EventState.SCHEDULED.value,
                        _iso(now),
                    ),
                )
                effective_id = event.provider_event_id
            else:
                # The provider_event_id is referenced by durable jobs and audit
                # rows. Keep that identity and update only operator-controlled
                # schedule metadata and the manual-override flag.
                effective_id = str(row["provider_event_id"])
                conn.execute(
                    """
                    UPDATE events SET ticker=?, fiscal_period=?, scheduled_at=?,
                        report_at=?, call_at=?, title=?, source_url=?,
                        updated_at=?, manual_override=1
                    WHERE provider_event_id=?
                    """,
                    (
                        event.ticker,
                        event.fiscal_period,
                        _iso(event.call_at),
                        _iso(event.report_at),
                        _iso(event.call_at),
                        event.title,
                        event.source_url,
                        _iso(now),
                        effective_id,
                    ),
                )
            conn.execute("COMMIT")
        armed = self.get_event(effective_id)
        if armed is None:  # pragma: no cover - transaction guarantees this
            raise RuntimeError(f"Unable to load armed event {effective_id}")
        return armed

    def recover_stale_leases(self, *, now: datetime | None = None) -> dict[str, int]:
        """Recover only expired worker leases and reconcile their audit state."""
        current = now or datetime.now(timezone.utc)
        cutoff = current - self.lease_timeout
        recovered_jobs = 0
        recovered_publications = 0
        running_to_queued = {
            "pre_release": (
                EventState.BASELINE_RUNNING.value,
                EventState.BASELINE_QUEUED.value,
            ),
            "release_to_call": (
                EventState.QUANT_RUNNING.value,
                EventState.QUANT_QUEUED.value,
            ),
            "post_call": (
                EventState.POST_CALL_RUNNING.value,
                EventState.POST_CALL_QUEUED.value,
            ),
        }
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            stale_jobs = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status='running' AND claimed_at IS NOT NULL AND claimed_at<=?
                """,
                (_iso(cutoff),),
            ).fetchall()
            for job in stale_jobs:
                retrying = job["attempts"] < job["max_attempts"]
                error = "worker lease expired before completion"
                conn.execute(
                    """
                    UPDATE jobs SET status=?, available_at=?, claimed_at=NULL,
                        finished_at=?, last_error=?
                    WHERE id=? AND status='running' AND claimed_at<=?
                    """,
                    (
                        JobStatus.PENDING.value if retrying else JobStatus.FAILED.value,
                        _iso(current) if retrying else job["available_at"],
                        None if retrying else _iso(current),
                        error,
                        job["id"],
                        _iso(cutoff),
                    ),
                )
                runs = conn.execute(
                    "SELECT id, stage, started_at FROM job_runs "
                    "WHERE job_id=? AND status='running'",
                    (job["id"],),
                ).fetchall()
                for run in runs:
                    duration_ms = max(
                        0,
                        int(
                            (current - _dt(run["started_at"])).total_seconds()
                            * 1000
                        ),
                    )
                    conn.execute(
                        """
                        UPDATE job_runs SET finished_at=?, duration_ms=?,
                            status='failed', error_summary=?
                        WHERE id=? AND status='running'
                        """,
                        (_iso(current), duration_ms, error, run["id"]),
                    )
                try:
                    stage = str(json.loads(job["payload_json"]).get("stage") or "")
                except (TypeError, ValueError):
                    stage = ""
                state_pair = running_to_queued.get(stage)
                if state_pair:
                    conn.execute(
                        """
                        UPDATE events SET state=?, last_error=?, updated_at=?
                        WHERE provider_event_id=? AND state=?
                        """,
                        (
                            state_pair[1] if retrying else EventState.FAILED.value,
                            error,
                            _iso(current),
                            job["provider_event_id"],
                            state_pair[0],
                        ),
                    )
                recovered_jobs += 1

            stale_publications = conn.execute(
                """
                SELECT * FROM artifact_publications
                WHERE status='running' AND claimed_at IS NOT NULL AND claimed_at<=?
                """,
                (_iso(cutoff),),
            ).fetchall()
            for publication in stale_publications:
                retrying = publication["attempts"] < publication["max_attempts"]
                conn.execute(
                    """
                    UPDATE artifact_publications SET status=?, available_at=?,
                        claimed_at=NULL, completed_at=?, last_error=?
                    WHERE id=? AND status='running' AND claimed_at<=?
                    """,
                    (
                        "pending" if retrying else "failed",
                        _iso(current) if retrying else publication["available_at"],
                        None if retrying else _iso(current),
                        "publication lease expired before completion",
                        publication["id"],
                        _iso(cutoff),
                    ),
                )
                recovered_publications += 1
            conn.execute("COMMIT")
        return {
            "jobs": recovered_jobs,
            "artifact_publications": recovered_publications,
        }

    def get_event(self, provider_event_id: str) -> MonitoredEvent | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM events WHERE provider_event_id=?", (provider_event_id,)
            ).fetchone()
        if row is None:
            return None
        event = EarningsEvent(
            provider_event_id=row["provider_event_id"],
            ticker=row["ticker"],
            fiscal_period=row["fiscal_period"],
            report_at=_dt(row["report_at"] or row["scheduled_at"]),  # type: ignore[arg-type]
            call_at=_dt(row["call_at"] or row["scheduled_at"]),  # type: ignore[arg-type]
            title=row["title"],
            source_url=row["source_url"],
        )
        return MonitoredEvent(
            event=event,
            state=EventState(row["state"]),
            transcript_fingerprint=row["transcript_fingerprint"],
            transcript_observed_at=_dt(row["transcript_observed_at"]),
            last_error=row["last_error"],
            updated_at=_dt(row["updated_at"]),  # type: ignore[arg-type]
            manual_override=bool(row["manual_override"]),
        )

    def get_event_for_period(
        self, ticker: str, fiscal_period: str
    ) -> MonitoredEvent | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT provider_event_id FROM events
                WHERE ticker=? AND fiscal_period=?
                """,
                (ticker.strip().upper(), fiscal_period.strip().upper()),
            ).fetchone()
        return self.get_event(row[0]) if row is not None else None

    def list_events(self, *, states: set[EventState] | None = None) -> list[MonitoredEvent]:
        with self._connect() as conn:
            if states:
                marks = ",".join("?" for _ in states)
                rows = conn.execute(
                    f"SELECT provider_event_id FROM events WHERE state IN ({marks}) ORDER BY report_at",
                    tuple(state.value for state in states),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT provider_event_id FROM events ORDER BY report_at"
                ).fetchall()
        return [event for row in rows if (event := self.get_event(row[0])) is not None]

    def list_event_rows(self) -> list[dict]:
        """Return raw operational event rows for alerts and dashboard facades."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events ORDER BY report_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def enqueue(
        self,
        *,
        idempotency_key: str,
        provider_event_id: str,
        payload: dict,
        max_attempts: int,
        available_at: datetime | None = None,
    ) -> bool:
        now = available_at or datetime.now(timezone.utc)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO jobs (
                    idempotency_key, provider_event_id, payload_json, status,
                    max_attempts, available_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    idempotency_key,
                    provider_event_id,
                    json.dumps(payload, sort_keys=True),
                    JobStatus.PENDING.value,
                    max_attempts,
                    _iso(now),
                ),
            )
            return cursor.rowcount == 1

    def claim_next_job(self, now: datetime | None = None) -> dict | None:
        current = now or datetime.now(timezone.utc)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM jobs
                WHERE status=? AND available_at<=? AND attempts<max_attempts
                ORDER BY available_at, id LIMIT 1
                """,
                (JobStatus.PENDING.value, _iso(current)),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            updated = conn.execute(
                """
                UPDATE jobs SET status=?, attempts=attempts+1, claimed_at=?
                WHERE id=? AND status=?
                """,
                (JobStatus.RUNNING.value, _iso(current), row["id"], JobStatus.PENDING.value),
            )
            conn.execute("COMMIT")
            if updated.rowcount != 1:
                return None
        result = dict(row)
        result["attempts"] += 1
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def finish_job(
        self,
        job_id: int,
        *,
        success: bool,
        error: str | None = None,
        retry_delay: timedelta = timedelta(seconds=60),
    ) -> None:
        current = datetime.now(timezone.utc)
        now = _iso(current)
        with self._connect() as conn:
            row = conn.execute("SELECT attempts, max_attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown job {job_id}")
            status = JobStatus.SUCCEEDED if success else JobStatus.FAILED
            if not success and row["attempts"] < row["max_attempts"]:
                status = JobStatus.PENDING
            next_available_at = (
                _iso(current + retry_delay)
                if status == JobStatus.PENDING
                else None
            )
            conn.execute(
                """
                UPDATE jobs SET status=?, finished_at=?, last_error=?,
                    available_at=CASE WHEN ?='pending' THEN ? ELSE available_at END
                WHERE id=?
                """,
                (
                    status.value,
                    now,
                    error,
                    status.value,
                    next_available_at,
                    job_id,
                ),
            )

    def notification_sent(self, key: str) -> bool:
        with self._connect() as conn:
            return conn.execute(
                "SELECT 1 FROM notifications "
                "WHERE notification_key=? AND status='sent'",
                (key,),
            ).fetchone() is not None

    def notification_key_exists(self, prefix: str) -> bool:
        with self._connect() as conn:
            return conn.execute(
                "SELECT 1 FROM notifications "
                "WHERE notification_key LIKE ? AND status='sent' LIMIT 1",
                (prefix + "%",),
            ).fetchone() is not None

    def claim_notification(self, key: str) -> bool:
        now = _iso(datetime.now(timezone.utc))
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO notifications(
                    notification_key, sent_at, status, claimed_at
                ) VALUES (?, ?, 'sending', ?)
                """,
                (key, now, now),
            )
            conn.execute("COMMIT")
            return cursor.rowcount == 1

    def release_notification(self, key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM notifications "
                "WHERE notification_key=? AND status='sending'",
                (key,),
            )
            return cursor.rowcount == 1

    def mark_notification_sent(self, key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO notifications(notification_key, sent_at, status, claimed_at)
                VALUES (?, ?, 'sent', NULL)
                ON CONFLICT(notification_key) DO UPDATE SET
                    sent_at=excluded.sent_at, status='sent', claimed_at=NULL
                """,
                (key, _iso(datetime.now(timezone.utc))),
            )
            return cursor.rowcount > 0

    def start_poll_cycle(self, started_at: datetime | None = None) -> int:
        started = started_at or datetime.now(timezone.utc)
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO poll_cycles(started_at, status) VALUES (?, 'running')",
                (_iso(started),),
            )
            return int(cursor.lastrowid)

    def finish_poll_cycle(
        self,
        cycle_id: int,
        *,
        result: dict | None = None,
        error: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        finished = finished_at or datetime.now(timezone.utc)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT started_at FROM poll_cycles WHERE id=?", (cycle_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown poll cycle {cycle_id}")
            duration_ms = max(
                0, int((finished - _dt(row["started_at"])).total_seconds() * 1000)
            )
            conn.execute(
                """
                UPDATE poll_cycles
                SET finished_at=?, duration_ms=?, status=?, result_json=?, error_summary=?
                WHERE id=?
                """,
                (
                    _iso(finished),
                    duration_ms,
                    "failed" if error else "succeeded",
                    json.dumps(result or {}, sort_keys=True),
                    error,
                    cycle_id,
                ),
            )

    def start_job_run(
        self,
        job: dict,
        *,
        stage: str,
        started_at: datetime | None = None,
    ) -> int:
        started = started_at or datetime.now(timezone.utc)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO job_runs(
                    job_id, provider_event_id, stage, attempt, started_at, status
                ) VALUES (?, ?, ?, ?, ?, 'running')
                """,
                (
                    job["id"],
                    job["provider_event_id"],
                    stage,
                    job["attempts"],
                    _iso(started),
                ),
            )
            return int(cursor.lastrowid)

    def finish_job_run(
        self,
        run_id: int,
        *,
        result: dict | None = None,
        error: str | None = None,
        status: str | None = None,
        finished_at: datetime | None = None,
    ) -> None:
        finished = finished_at or datetime.now(timezone.utc)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT started_at FROM job_runs WHERE id=?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown job run {run_id}")
            duration_ms = max(
                0, int((finished - _dt(row["started_at"])).total_seconds() * 1000)
            )
            conn.execute(
                """
                UPDATE job_runs
                SET finished_at=?, duration_ms=?, status=?, result_json=?, error_summary=?
                WHERE id=?
                """,
                (
                    _iso(finished),
                    duration_ms,
                    status or ("failed" if error else "succeeded"),
                    json.dumps(result or {}, sort_keys=True, default=str),
                    error,
                    run_id,
                ),
            )

    def enqueue_artifact_publication(
        self,
        *,
        publication_key: str,
        provider_event_id: str,
        fingerprint: str,
        payload: dict,
        max_attempts: int,
        available_at: datetime | None = None,
    ) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO artifact_publications(
                    publication_key, provider_event_id, fingerprint, payload_json,
                    status, max_attempts, available_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    publication_key,
                    provider_event_id,
                    fingerprint,
                    json.dumps(payload, sort_keys=True, default=str),
                    max_attempts,
                    _iso(available_at or datetime.now(timezone.utc)),
                ),
            )
            return cursor.rowcount == 1

    def claim_artifact_publication(self, now: datetime | None = None) -> dict | None:
        current = now or datetime.now(timezone.utc)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT * FROM artifact_publications
                WHERE status='pending' AND available_at<=? AND attempts<max_attempts
                ORDER BY available_at, id LIMIT 1
                """,
                (_iso(current),),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                return None
            updated = conn.execute(
                """
                UPDATE artifact_publications
                SET status='running', attempts=attempts+1, claimed_at=?
                WHERE id=? AND status='pending'
                """,
                (_iso(current), row["id"]),
            )
            conn.execute("COMMIT")
            if updated.rowcount != 1:
                return None
        result = dict(row)
        result["attempts"] += 1
        result["payload"] = json.loads(result.pop("payload_json"))
        return result

    def finish_artifact_publication(
        self,
        publication_id: int,
        *,
        success: bool,
        manifest_uri: str | None = None,
        error: str | None = None,
        retry_delay: timedelta = timedelta(seconds=60),
        finished_at: datetime | None = None,
    ) -> None:
        current = finished_at or datetime.now(timezone.utc)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT attempts, max_attempts FROM artifact_publications WHERE id=?",
                (publication_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"Unknown artifact publication {publication_id}")
            retrying = not success and row["attempts"] < row["max_attempts"]
            conn.execute(
                """
                UPDATE artifact_publications SET status=?, available_at=?,
                    completed_at=?, manifest_uri=?, last_error=?
                WHERE id=?
                """,
                (
                    "pending" if retrying else ("succeeded" if success else "failed"),
                    _iso(current + retry_delay) if retrying else _iso(current),
                    _iso(current) if success else None,
                    manifest_uri,
                    error,
                    publication_id,
                ),
            )

    def list_poll_cycles(self, *, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM poll_cycles ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def list_job_runs(
        self, *, provider_event_id: str | None = None, limit: int = 200
    ) -> list[dict]:
        with self._connect() as conn:
            if provider_event_id:
                rows = conn.execute(
                    """
                    SELECT * FROM job_runs WHERE provider_event_id=?
                    ORDER BY started_at DESC LIMIT ?
                    """,
                    (provider_event_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM job_runs ORDER BY started_at DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]

    def list_artifact_publications(self, *, limit: int = 100) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM artifact_publications
                ORDER BY available_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
