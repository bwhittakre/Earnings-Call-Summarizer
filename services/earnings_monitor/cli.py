"""Command-line entrypoints for diagnostics and local polling."""

from __future__ import annotations

import argparse
import json
import logging
import time

from .config import MonitorConfig
from .diagnostics import diagnostics_ok, run_startup_diagnostics
from .freshness import AlwaysFreshProbe
from .notifications import SMTPMailSender, TwoEmailNotifier
from .providers import LocalInboxProvider
from .service import EarningsMonitor
from .state import OperationalState
from .workflow import LazyStructuredNarrativeWorkflow


def build_local_monitor(config: MonitorConfig) -> EarningsMonitor:
    if config.provider != "local":
        raise RuntimeError(
            "CLI supports the local provider directly. Inject QuartrAdapter from an API/MCP host."
        )
    state = OperationalState(config.database_path)
    state.initialize()
    provider = LocalInboxProvider(config.inbox_path)
    workflow = LazyStructuredNarrativeWorkflow(config.repo_root)
    notifier = None
    if config.email_enabled:
        notifier = TwoEmailNotifier(
            state=state,
            sender=SMTPMailSender(config),
            sender_address=config.smtp_from or "",
            recipients=config.smtp_to,
        )
    return EarningsMonitor(
        config=config,
        state=state,
        event_provider=provider,
        transcript_provider=provider,
        freshness=AlwaysFreshProbe(),
        workflow=workflow,
        notifier=notifier,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local earnings-call monitor")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("diagnose", help="Validate local startup access")
    subparsers.add_parser("once", help="Run one discovery and processing cycle")
    run_parser = subparsers.add_parser("run", help="Run continuously")
    run_parser.add_argument("--interval", type=int, default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    config = MonitorConfig.from_env()
    monitor = build_local_monitor(config)
    workflow = monitor.workflow
    diagnostics = run_startup_diagnostics(
        config,
        provider_check=lambda: (
            config.inbox_path.is_dir(),
            str(config.inbox_path),
        ),
        workflow_check=getattr(workflow, "available", None),
    )
    if args.command == "diagnose":
        for check in diagnostics:
            print(f"{'OK' if check.ok else 'FAIL'} {check.name}: {check.detail}")
        return 0 if diagnostics_ok(diagnostics) else 2
    if not diagnostics_ok(diagnostics):
        for check in diagnostics:
            if check.required and not check.ok:
                logging.error("%s: %s", check.name, check.detail)
        return 2
    if args.command == "once":
        print(json.dumps(monitor.run_cycle(), sort_keys=True))
        return 0
    interval = args.interval or config.poll_interval_seconds
    if interval < 1:
        parser.error("--interval must be positive")
    try:
        while True:
            logging.info("cycle=%s", monitor.run_cycle())
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
