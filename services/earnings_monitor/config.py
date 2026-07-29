"""Configuration loaded from environment variables or explicit mappings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

PILOT_TICKERS = ("AMZN", "MSFT", "NVDA", "AAPL")


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int, *, minimum: int = 1) -> int:
    parsed = default if value is None else int(value)
    if parsed < minimum:
        raise ValueError(f"Expected value >= {minimum}, got {parsed}")
    return parsed


@dataclass(frozen=True)
class MonitorConfig:
    repo_root: Path
    database_path: Path
    inbox_path: Path
    tickers: tuple[str, ...] = PILOT_TICKERS
    provider: str = "local"
    poll_interval_seconds: int = 300
    stabilization_seconds: int = 300
    minimum_transcript_chars: int = 1_000
    max_job_attempts: int = 3
    workflow_profile: str = "new_quarter"
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    smtp_to: tuple[str, ...] = ()
    smtp_starttls: bool = True

    @classmethod
    def from_env(
        cls,
        env: Mapping[str, str] | None = None,
        *,
        repo_root: Path | None = None,
    ) -> "MonitorConfig":
        values = os.environ if env is None else env
        root = Path(repo_root or values.get("EARNINGS_MONITOR_REPO_ROOT") or Path.cwd()).resolve()
        state_dir = root / "services" / "earnings_monitor" / "state"
        raw_tickers = values.get("EARNINGS_MONITOR_TICKERS", ",".join(PILOT_TICKERS))
        tickers = tuple(dict.fromkeys(t.strip().upper() for t in raw_tickers.split(",") if t.strip()))
        unsupported = set(tickers) - set(PILOT_TICKERS)
        if not tickers or unsupported:
            raise ValueError(f"Tickers must be a non-empty subset of {PILOT_TICKERS}; invalid={sorted(unsupported)}")
        recipients = tuple(
            address.strip()
            for address in values.get("EARNINGS_MONITOR_SMTP_TO", "").split(",")
            if address.strip()
        )
        return cls(
            repo_root=root,
            database_path=Path(values.get("EARNINGS_MONITOR_DB", state_dir / "monitor.sqlite3")),
            inbox_path=Path(
                values.get(
                    "EARNINGS_MONITOR_INBOX",
                    root / "earnings-scraper-main" / "earnings-scraper-main" / "inbox",
                )
            ),
            tickers=tickers,
            provider=values.get("EARNINGS_MONITOR_PROVIDER", "local").strip().lower(),
            poll_interval_seconds=_int(values.get("EARNINGS_MONITOR_POLL_SECONDS"), 300),
            stabilization_seconds=_int(values.get("EARNINGS_MONITOR_STABILIZATION_SECONDS"), 300, minimum=0),
            minimum_transcript_chars=_int(values.get("EARNINGS_MONITOR_MIN_CHARS"), 1_000),
            max_job_attempts=_int(values.get("EARNINGS_MONITOR_MAX_ATTEMPTS"), 3),
            workflow_profile=values.get("EARNINGS_MONITOR_WORKFLOW", "new_quarter").strip(),
            smtp_host=values.get("EARNINGS_MONITOR_SMTP_HOST"),
            smtp_port=_int(values.get("EARNINGS_MONITOR_SMTP_PORT"), 587),
            smtp_username=values.get("EARNINGS_MONITOR_SMTP_USERNAME"),
            smtp_password=values.get("EARNINGS_MONITOR_SMTP_PASSWORD"),
            smtp_from=values.get("EARNINGS_MONITOR_SMTP_FROM"),
            smtp_to=recipients,
            smtp_starttls=_bool(values.get("EARNINGS_MONITOR_SMTP_STARTTLS"), True),
        )

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from and self.smtp_to)
