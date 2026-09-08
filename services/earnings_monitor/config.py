"""Configuration loaded from environment variables or explicit mappings."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

PILOT_TICKERS = ("MSFT", "AAPL", "NVDA", "MU")
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")


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
    event_manifest_path: Path | None = None
    dataset_path: Path | None = None
    history_source_path: Path | None = None
    tickers: tuple[str, ...] = PILOT_TICKERS
    provider: str = "manual"
    monitor_universe_mode: str = "overlays"
    monitor_excluded_tickers: tuple[str, ...] = ()
    poll_interval_seconds: int = 300
    stabilization_seconds: int = 300
    minimum_transcript_chars: int = 1_000
    require_live_growth: bool = True
    max_job_attempts: int = 3
    retry_base_seconds: int = 60
    lease_timeout_seconds: int = 60 * 60
    quant_start_offset_seconds: int = 90 * 60
    transcript_start_delay_seconds: int = 45 * 60
    transcript_timeout_seconds: int = 3 * 60 * 60
    refresh_history_after_workflow: bool = False
    research_regen_after_post_call: bool = True
    desk_trees_after_post_call: bool = True
    desk_autopilot_after_post_call: bool = True
    desk_autopilot_budget_usd: float = 1.0
    scorecard_after_post_call: bool = True
    research_regen_debounce_seconds: int = 60
    research_regen_idle_seconds: int = 30
    research_min_calendar_quarter: str = "2016-Q2"
    research_sector: str = "xlk_tech"
    workflow_profile: str = "new_quarter"
    r2_account_id: str | None = None
    r2_endpoint_url: str | None = None
    r2_bucket: str | None = None
    r2_prefix: str = "roz"
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    r2_publish_max_attempts: int = 5
    stuck_event_seconds: int = 2 * 60 * 60
    repeated_failure_threshold: int = 2
    dashboard_url: str = "http://localhost:8501"
    artifact_public_base_url: str | None = None
    smtp_mode: str = "local"
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
        invalid = sorted(ticker for ticker in tickers if not _TICKER_RE.fullmatch(ticker))
        if not tickers or invalid:
            raise ValueError(
                f"Tickers must be non-empty valid exchange symbols; invalid={invalid}"
            )
        universe_mode = (
            values.get("EARNINGS_MONITOR_UNIVERSE_MODE", "overlays").strip().lower()
        )
        if universe_mode not in {"overlays", "book"}:
            raise ValueError(
                "EARNINGS_MONITOR_UNIVERSE_MODE must be overlays or book"
            )
        excluded_tickers = tuple(
            dict.fromkeys(
                ticker.strip().upper()
                for ticker in values.get(
                    "EARNINGS_MONITOR_EXCLUDE_TICKERS", ""
                ).split(",")
                if ticker.strip()
            )
        )
        recipients = tuple(
            address.strip()
            for address in values.get(
                "EARNINGS_MONITOR_SMTP_TO",
                "developer@localhost"
                if values.get("EARNINGS_MONITOR_SMTP_MODE", "local").strip().lower()
                == "local"
                else "",
            ).split(",")
            if address.strip()
        )
        smtp_mode = values.get("EARNINGS_MONITOR_SMTP_MODE", "local").strip().lower()
        if smtp_mode not in {"local", "microsoft365", "custom"}:
            raise ValueError(
                "EARNINGS_MONITOR_SMTP_MODE must be local, microsoft365, or custom"
            )
        smtp_host_default = {
            "local": "mailpit",
            "microsoft365": "smtp.office365.com",
            "custom": "",
        }[smtp_mode]
        smtp_port_default = 1025 if smtp_mode == "local" else 587
        smtp_starttls_default = smtp_mode != "local"
        account_id = values.get("EARNINGS_MONITOR_R2_ACCOUNT_ID")
        endpoint = values.get("EARNINGS_MONITOR_R2_ENDPOINT_URL")
        if not endpoint and account_id:
            endpoint = f"https://{account_id}.r2.cloudflarestorage.com"
        return cls(
            repo_root=root,
            database_path=Path(values.get("EARNINGS_MONITOR_DB", state_dir / "monitor.sqlite3")),
            inbox_path=Path(
                values.get(
                    "EARNINGS_MONITOR_INBOX",
                    root / "earnings-scraper-main" / "earnings-scraper-main" / "inbox",
                )
            ),
            event_manifest_path=Path(
                values.get(
                    "EARNINGS_MONITOR_EVENT_MANIFESTS",
                    root / "services" / "earnings_monitor" / "watched_events",
                )
            ),
            dataset_path=Path(
                values.get(
                    "EARNINGS_MONITOR_DATASET",
                    root / "data" / "earnings_monitor" / "company_quarters.parquet",
                )
            ),
            history_source_path=Path(
                values.get(
                    "EARNINGS_MONITOR_HISTORY_SOURCE",
                    root / "Structured Narrative" / "output",
                )
            ),
            tickers=tickers,
            provider=values.get("EARNINGS_MONITOR_PROVIDER", "manual").strip().lower(),
            monitor_universe_mode=universe_mode,
            monitor_excluded_tickers=excluded_tickers,
            poll_interval_seconds=_int(values.get("EARNINGS_MONITOR_POLL_SECONDS"), 300),
            stabilization_seconds=_int(values.get("EARNINGS_MONITOR_STABILIZATION_SECONDS"), 300, minimum=0),
            minimum_transcript_chars=_int(values.get("EARNINGS_MONITOR_MIN_CHARS"), 1_000),
            require_live_growth=_bool(
                values.get("EARNINGS_MONITOR_REQUIRE_LIVE_GROWTH"), True
            ),
            max_job_attempts=_int(values.get("EARNINGS_MONITOR_MAX_ATTEMPTS"), 3),
            retry_base_seconds=_int(
                values.get("EARNINGS_MONITOR_RETRY_BASE_SECONDS"), 60
            ),
            lease_timeout_seconds=_int(
                values.get("EARNINGS_MONITOR_LEASE_TIMEOUT_SECONDS"), 60 * 60
            ),
            quant_start_offset_seconds=_int(
                values.get("EARNINGS_MONITOR_QUANT_START_OFFSET_SECONDS"),
                90 * 60,
                minimum=0,
            ),
            transcript_start_delay_seconds=_int(
                values.get("EARNINGS_MONITOR_TRANSCRIPT_START_DELAY_SECONDS"),
                45 * 60,
                minimum=0,
            ),
            transcript_timeout_seconds=_int(
                values.get("EARNINGS_MONITOR_TRANSCRIPT_TIMEOUT_SECONDS"),
                3 * 60 * 60,
            ),
            refresh_history_after_workflow=_bool(
                values.get("EARNINGS_MONITOR_REFRESH_HISTORY"), False
            ),
            research_regen_after_post_call=_bool(
                values.get("EARNINGS_MONITOR_RESEARCH_REGEN"), True
            ),
            desk_trees_after_post_call=_bool(
                values.get("EARNINGS_MONITOR_DESK_TREES"), True
            ),
            desk_autopilot_after_post_call=_bool(
                values.get("EARNINGS_MONITOR_DESK_AUTOPILOT"), True
            ),
            desk_autopilot_budget_usd=float(
                values.get("EARNINGS_MONITOR_DESK_AUTOPILOT_BUDGET_USD") or "1.0"
            ),
            scorecard_after_post_call=_bool(
                values.get("EARNINGS_MONITOR_SCORECARD"), True
            ),
            research_regen_debounce_seconds=_int(
                values.get("EARNINGS_MONITOR_RESEARCH_REGEN_DEBOUNCE_SECONDS"),
                60,
                minimum=0,
            ),
            research_regen_idle_seconds=_int(
                values.get("EARNINGS_MONITOR_RESEARCH_REGEN_IDLE_SECONDS"),
                30,
            ),
            research_min_calendar_quarter=values.get(
                "EARNINGS_MONITOR_RESEARCH_MIN_CALENDAR_QUARTER", "2016-Q2"
            ).strip(),
            research_sector=values.get(
                "EARNINGS_MONITOR_RESEARCH_SECTOR", "xlk_tech"
            ).strip(),
            workflow_profile=values.get("EARNINGS_MONITOR_WORKFLOW", "new_quarter").strip(),
            r2_account_id=account_id,
            r2_endpoint_url=endpoint,
            r2_bucket=values.get("EARNINGS_MONITOR_R2_BUCKET") or None,
            r2_prefix=values.get("EARNINGS_MONITOR_R2_PREFIX", "roz").strip("/"),
            r2_access_key_id=values.get("EARNINGS_MONITOR_R2_ACCESS_KEY_ID") or None,
            r2_secret_access_key=values.get("EARNINGS_MONITOR_R2_SECRET_ACCESS_KEY") or None,
            r2_publish_max_attempts=_int(
                values.get("EARNINGS_MONITOR_R2_MAX_ATTEMPTS"), 5
            ),
            stuck_event_seconds=_int(
                values.get("EARNINGS_MONITOR_STUCK_EVENT_SECONDS"), 2 * 60 * 60
            ),
            repeated_failure_threshold=_int(
                values.get("EARNINGS_MONITOR_REPEATED_FAILURE_THRESHOLD"), 2
            ),
            dashboard_url=values.get(
                "EARNINGS_MONITOR_DASHBOARD_URL", "http://localhost:8501"
            ).rstrip("/"),
            artifact_public_base_url=(
                values.get("EARNINGS_MONITOR_ARTIFACT_PUBLIC_BASE_URL") or None
            ),
            smtp_mode=smtp_mode,
            smtp_host=values.get("EARNINGS_MONITOR_SMTP_HOST", smtp_host_default) or None,
            smtp_port=_int(
                values.get("EARNINGS_MONITOR_SMTP_PORT"), smtp_port_default
            ),
            smtp_username=values.get("EARNINGS_MONITOR_SMTP_USERNAME"),
            smtp_password=values.get("EARNINGS_MONITOR_SMTP_PASSWORD"),
            smtp_from=values.get(
                "EARNINGS_MONITOR_SMTP_FROM",
                "earnings-monitor@localhost" if smtp_mode == "local" else "",
            )
            or values.get("EARNINGS_MONITOR_SMTP_USERNAME")
            or None,
            smtp_to=recipients,
            smtp_starttls=_bool(
                values.get("EARNINGS_MONITOR_SMTP_STARTTLS"),
                smtp_starttls_default,
            ),
        )

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host and self.smtp_from and self.smtp_to)

    @property
    def smtp_setup_issues(self) -> tuple[str, ...]:
        if self.smtp_mode != "microsoft365":
            return ()
        missing = [
            name
            for name, value in (
                ("username", self.smtp_username),
                ("password", self.smtp_password),
                ("from", self.smtp_from),
                ("to", self.smtp_to),
            )
            if not value
        ]
        if self.smtp_host != "smtp.office365.com":
            missing.append("host=smtp.office365.com")
        if self.smtp_port != 587:
            missing.append("port=587")
        if not self.smtp_starttls:
            missing.append("STARTTLS")
        return tuple(missing)

    @property
    def r2_enabled(self) -> bool:
        values = (
            self.r2_endpoint_url,
            self.r2_bucket,
            self.r2_access_key_id,
            self.r2_secret_access_key,
        )
        if not any(values):
            return False
        if not all(values):
            raise ValueError(
                "R2 publishing requires endpoint/account, bucket, access key ID, "
                "and secret access key"
            )
        return True
