"""SQLite-backed operational state with atomic job claiming."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from .models import EarningsEvent, EventState, JobStatus, MonitoredEvent


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class OperationalState:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def initialize(self) -> None:
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
                    sent_at TEXT NOT NULL
                );
                """
            )
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(events)")}
            if "report_at" not in columns:
                conn.execute("ALTER TABLE events ADD COLUMN report_at TEXT")
            if "call_at" not in columns:
                conn.execute("ALTER TABLE events ADD COLUMN call_at TEXT")
            conn.execute(
                "UPDATE events SET report_at=COALESCE(report_at, scheduled_at), "
                "call_at=COALESCE(call_at, scheduled_at)"
            )
            conn.execute(
                """
                UPDATE events SET state=CASE
                    WHEN state='succeeded' THEN 'complete'
                    WHEN state IN (
                        'call_started', 'transcript_pending', 'transcript_unstable',
                        'ready', 'queued', 'running', 'failed'
                    ) THEN 'scheduled'
                    ELSE state
                END
                """
            )

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
                    last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider_event_id) DO UPDATE SET
                    ticker=excluded.ticker, fiscal_period=excluded.fiscal_period,
                    scheduled_at=excluded.scheduled_at, report_at=excluded.report_at,
                    call_at=excluded.call_at, title=excluded.title,
                    source_url=excluded.source_url, state=excluded.state,
                    transcript_fingerprint=excluded.transcript_fingerprint,
                    transcript_observed_at=excluded.transcript_observed_at,
                    last_error=excluded.last_error, updated_at=excluded.updated_at
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
                ),
            )

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
        )

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

    def finish_job(self, job_id: int, *, success: bool, error: str | None = None) -> None:
        now = _iso(datetime.now(timezone.utc))
        with self._connect() as conn:
            row = conn.execute("SELECT attempts, max_attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(f"Unknown job {job_id}")
            status = JobStatus.SUCCEEDED if success else JobStatus.FAILED
            if not success and row["attempts"] < row["max_attempts"]:
                status = JobStatus.PENDING
            conn.execute(
                """
                UPDATE jobs SET status=?, finished_at=?, last_error=?,
                    available_at=CASE WHEN ?='pending' THEN ? ELSE available_at END
                WHERE id=?
                """,
                (status.value, now, error, status.value, now, job_id),
            )

    def notification_sent(self, key: str) -> bool:
        with self._connect() as conn:
            return conn.execute(
                "SELECT 1 FROM notifications WHERE notification_key=?", (key,)
            ).fetchone() is not None

    def mark_notification_sent(self, key: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT OR IGNORE INTO notifications(notification_key, sent_at) VALUES (?, ?)",
                (key, _iso(datetime.now(timezone.utc))),
            )
            return cursor.rowcount == 1
