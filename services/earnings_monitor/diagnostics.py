"""Startup access checks that avoid external calls unless explicitly injected."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import MonitorConfig


@dataclass(frozen=True)
class Diagnostic:
    name: str
    ok: bool
    detail: str
    required: bool = True


def run_startup_diagnostics(
    config: MonitorConfig,
    *,
    provider_check: Callable[[], Any] | None = None,
    freshness_check: Callable[[], Any] | None = None,
    workflow_check: Callable[[], Any] | None = None,
) -> list[Diagnostic]:
    checks: list[Diagnostic] = []
    try:
        config.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(config.database_path)
        connection.execute("SELECT 1")
        connection.close()
        checks.append(Diagnostic("sqlite", True, str(config.database_path)))
    except Exception as exc:
        checks.append(Diagnostic("sqlite", False, str(exc)))

    inbox = Path(config.inbox_path)
    checks.append(
        Diagnostic(
            "inbox",
            inbox.is_dir(),
            str(inbox) if inbox.is_dir() else f"directory not found: {inbox}",
            required=config.provider == "local",
        )
    )
    checks.append(
        Diagnostic(
            "smtp",
            config.email_enabled,
            "configured" if config.email_enabled else "disabled or incomplete",
            required=False,
        )
    )
    for name, check in (
        ("provider", provider_check),
        ("snowflake", freshness_check),
        ("workflow", workflow_check),
    ):
        if check is None:
            checks.append(Diagnostic(name, True, "check not configured", required=False))
            continue
        try:
            result = check()
            ok, detail = result if isinstance(result, tuple) else (bool(result), str(result))
            checks.append(Diagnostic(name, bool(ok), str(detail)))
        except Exception as exc:
            checks.append(Diagnostic(name, False, str(exc)))
    return checks


def diagnostics_ok(diagnostics: list[Diagnostic]) -> bool:
    return all(item.ok or not item.required for item in diagnostics)
