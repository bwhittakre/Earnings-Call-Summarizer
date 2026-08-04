"""Command-line entrypoints for diagnostics and local polling."""

from __future__ import annotations

import argparse
import json
import logging
import time
from datetime import datetime, timedelta

from .config import MonitorConfig
from .diagnostics import diagnostics_ok, run_startup_diagnostics
from .freshness import StructuredNarrativeFreshnessProbe
from .models import EarningsEvent
from .notifications import SMTPMailSender, TwoEmailNotifier
from .providers import (
    LocalInboxProvider,
    ManualEventProvider,
    WatchedEventManifestProvider,
)
from .service import EarningsMonitor
from .state import OperationalState
from .storage import CompletedEventArtifactPublisher, S3ArtifactStore
from .workflow import LazyStructuredNarrativeWorkflow


def build_local_monitor(config: MonitorConfig) -> EarningsMonitor:
    if config.provider not in {"local", "manual", "watched"}:
        raise RuntimeError(
            "CLI provider must be 'manual', 'local', or 'watched'."
        )
    state = OperationalState(
        config.database_path,
        lease_timeout=timedelta(seconds=config.lease_timeout_seconds),
    )
    state.initialize()
    transcript_provider = LocalInboxProvider(config.inbox_path)
    if config.provider == "manual":
        event_provider = ManualEventProvider()
    elif config.provider == "watched":
        if config.event_manifest_path is None:
            raise RuntimeError("watched provider requires EARNINGS_MONITOR_EVENT_MANIFESTS")
        config.event_manifest_path.mkdir(parents=True, exist_ok=True)
        event_provider = WatchedEventManifestProvider(config.event_manifest_path)
    else:
        event_provider = transcript_provider
    freshness = StructuredNarrativeFreshnessProbe(config.repo_root)
    workflow = LazyStructuredNarrativeWorkflow(
        config.repo_root, spine_tickers=config.tickers
    )
    notifier = None
    if config.email_enabled:
        notifier = TwoEmailNotifier(
            state=state,
            sender=SMTPMailSender(config),
            sender_address=config.smtp_from or "",
            recipients=config.smtp_to,
            config=config,
        )
    artifact_publisher = None
    if config.r2_enabled:
        store = S3ArtifactStore(
            config.r2_bucket or "",
            prefix=config.r2_prefix,
            endpoint_url=config.r2_endpoint_url,
            access_key_id=config.r2_access_key_id,
            secret_access_key=config.r2_secret_access_key,
        )
        artifact_publisher = CompletedEventArtifactPublisher(store, config.repo_root)
    return EarningsMonitor(
        config=config,
        state=state,
        event_provider=event_provider,
        transcript_provider=transcript_provider,
        freshness=freshness,
        workflow=workflow,
        notifier=notifier,
        artifact_publisher=artifact_publisher,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Roz local earnings-call monitor")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("diagnose", help="Validate local startup access")
    subparsers.add_parser("once", help="Run one discovery and processing cycle")
    arm_parser = subparsers.add_parser(
        "arm", help="Arm or correct one manually scheduled earnings event"
    )
    arm_parser.add_argument("--ticker", required=True)
    arm_parser.add_argument("--period", required=True)
    arm_parser.add_argument("--report-at", required=True)
    arm_parser.add_argument("--call-at", required=True)
    arm_parser.add_argument("--event-id")
    arm_parser.add_argument("--title", default="")
    arm_parser.add_argument("--source-url")
    arm_parser.add_argument(
        "--first-print",
        action="store_true",
        help=(
            "First-Print mode: skip prior-quarter pre_release baseline and "
            "post-call delta/surprise/novelty comparisons"
        ),
    )
    arm_parser.add_argument(
        "--onboard",
        action="store_true",
        help=(
            "Onboard mode: pull lookback history, scaffold CompanyProfile, "
            "run quant + batch LLM + panel before baseline (mutually exclusive "
            "with --first-print)"
        ),
    )
    arm_parser.add_argument(
        "--onboard-dry-run",
        action="store_true",
        help="With --onboard, plan steps without executing network/LLM work",
    )
    onboard_parser = subparsers.add_parser(
        "onboard",
        help="Run Onboard orchestrator for a ticker/period (history → score → panel)",
    )
    onboard_parser.add_argument("--ticker", required=True)
    onboard_parser.add_argument("--period", required=True)
    onboard_parser.add_argument("--report-at", required=True)
    onboard_parser.add_argument("--call-at", default=None)
    onboard_parser.add_argument("--company-name", default="")
    onboard_parser.add_argument("--dry-run", action="store_true")
    onboard_parser.add_argument("--skip-pull", action="store_true")
    onboard_parser.add_argument("--skip-ids", action="store_true")
    onboard_parser.add_argument("--skip-fiscal", action="store_true")
    onboard_parser.add_argument("--skip-quant", action="store_true")
    onboard_parser.add_argument("--skip-llm", action="store_true")
    onboard_parser.add_argument("--skip-panel", action="store_true")
    onboard_parser.add_argument(
        "--force-onboard",
        action="store_true",
        help="Run Onboard even if mode router would classify as standard",
    )
    onboard_parser.add_argument(
        "--arm",
        action="store_true",
        help="After Onboard, arm the event (requires ticker on allowlist)",
    )
    run_parser = subparsers.add_parser("run", help="Run continuously")
    run_parser.add_argument("--interval", type=int, default=None)
    worker_parser = subparsers.add_parser(
        "worker", help="Run the local workflow job processor"
    )
    worker_parser.add_argument("--interval", type=int, default=None)
    regen_parser = subparsers.add_parser(
        "research-regen",
        help="Regenerate Rank IC + consolidated HTML once (dirty book or --force)",
    )
    regen_parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even when the research book is not marked dirty",
    )
    regen_parser.add_argument(
        "--no-debounce",
        action="store_true",
        help="Ignore debounce delay when the book is dirty",
    )
    subparsers.add_parser(
        "research-regen-loop",
        help="Poll the dirty flag and regenerate Rank IC + consolidated HTML",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO)

    config = MonitorConfig.from_env()
    if args.command in {"research-regen", "research-regen-loop"}:
        from .research_regen import run_research_regen_loop, run_research_regen_once

        state = OperationalState(
            config.database_path,
            lease_timeout=timedelta(seconds=config.lease_timeout_seconds),
        )
        state.initialize()
        if args.command == "research-regen-loop":
            try:
                run_research_regen_loop(config, state)
            except KeyboardInterrupt:
                return 0
            return 0
        result = run_research_regen_once(
            config,
            state,
            force=bool(args.force),
            honor_debounce=not bool(args.no_debounce),
        )
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "skipped": result.skipped,
                    "skip_reason": result.skip_reason,
                    "triggered_by": result.triggered_by,
                    "started_at": result.started_at,
                    "finished_at": result.finished_at,
                    "commands": [
                        {
                            "name": item.name,
                            "returncode": item.returncode,
                            "duration_seconds": round(item.duration_seconds, 3),
                        }
                        for item in result.commands
                    ],
                },
                sort_keys=True,
            )
        )
        return 0 if result.ok else 1

    if args.command == "onboard":
        from .models import EventState, WorkflowMode
        from .onboard import run_onboard

        ticker = args.ticker.strip().upper()
        try:
            report_at = datetime.fromisoformat(
                args.report_at.strip().replace("Z", "+00:00")
            )
            if report_at.tzinfo is None:
                raise ValueError("report_at must include a UTC offset")
            call_raw = args.call_at or args.report_at
            call_at = datetime.fromisoformat(
                str(call_raw).strip().replace("Z", "+00:00")
            )
            if call_at.tzinfo is None:
                raise ValueError("call_at must include a UTC offset")
        except ValueError as exc:
            parser.error(str(exc))

        result = run_onboard(
            repo_root=config.repo_root,
            ticker=ticker,
            fiscal_period=args.period.upper(),
            report_at=report_at,
            company_name=args.company_name or ticker,
            dry_run=bool(args.dry_run),
            skip_pull=bool(args.skip_pull),
            skip_ids=bool(args.skip_ids),
            skip_fiscal=bool(args.skip_fiscal),
            skip_quant=bool(args.skip_quant),
            skip_llm=bool(args.skip_llm),
            skip_panel=bool(args.skip_panel),
            force_mode="onboard" if args.force_onboard else None,
            configured_tickers=config.tickers,
        )
        payload = result.to_dict()
        if args.arm:
            if ticker not in config.tickers:
                parser.error(
                    f"{ticker} is not in EARNINGS_MONITOR_TICKERS={config.tickers}. "
                    f"{result.allowlist_guidance}"
                )
            monitor = build_local_monitor(config)
            if result.status == "first_print_fallback":
                initial = EventState.SCHEDULED
                mode = WorkflowMode.FIRST_PRINT.value
                first_print = True
            elif result.status == "onboarding_blocked":
                initial = EventState.ONBOARDING_BLOCKED
                mode = WorkflowMode.ONBOARD.value
                first_print = False
            elif result.status in {"completed", "already_standard"}:
                initial = EventState.SCHEDULED
                mode = (
                    WorkflowMode.STANDARD.value
                    if result.status == "already_standard"
                    else WorkflowMode.ONBOARD.value
                )
                first_print = False
            else:
                initial = EventState.ONBOARDING_BLOCKED
                mode = WorkflowMode.ONBOARD.value
                first_print = False
            event = EarningsEvent(
                provider_event_id=f"manual:{ticker}:{args.period.upper()}",
                ticker=ticker,
                fiscal_period=args.period.upper(),
                report_at=report_at,
                call_at=call_at,
            )
            monitored = monitor.state.arm_event(
                event,
                first_print=first_print,
                workflow_mode=mode,
                initial_state=initial,
            )
            if result.error and initial == EventState.ONBOARDING_BLOCKED:
                monitored.last_error = result.error
                monitor.state.upsert_event(monitored)
            payload["armed"] = {
                "event_id": monitored.event.provider_event_id,
                "state": monitored.state.value,
                "workflow_mode": monitored.workflow_mode,
                "first_print": monitored.first_print,
            }
        print(json.dumps(payload, sort_keys=True, default=str))
        if result.status == "first_print_fallback":
            return 3
        if result.status in {"onboarding_blocked", "failed"}:
            return 2
        return 0

    monitor = build_local_monitor(config)
    if args.command == "arm":
        ticker = args.ticker.strip().upper()
        if ticker not in config.tickers:
            parser.error(
                f"{ticker} is not in EARNINGS_MONITOR_TICKERS={config.tickers}"
            )
        if bool(getattr(args, "first_print", False)) and bool(
            getattr(args, "onboard", False)
        ):
            parser.error("--first-print and --onboard are mutually exclusive")
        try:
            report_at = datetime.fromisoformat(
                args.report_at.strip().replace("Z", "+00:00")
            )
            call_at = datetime.fromisoformat(
                args.call_at.strip().replace("Z", "+00:00")
            )
            if report_at.tzinfo is None or call_at.tzinfo is None:
                raise ValueError("timestamps must include a UTC offset")
            event = EarningsEvent(
                provider_event_id=(
                    args.event_id or f"manual:{ticker}:{args.period.upper()}"
                ),
                ticker=ticker,
                fiscal_period=args.period.upper(),
                report_at=report_at,
                call_at=call_at,
                title=args.title,
                source_url=args.source_url,
            )
        except ValueError as exc:
            parser.error(str(exc))

        onboard_payload = None
        initial_state = None
        workflow_mode = "first_print" if args.first_print else "standard"
        if args.onboard:
            from .models import EventState, WorkflowMode
            from .onboard import run_onboard

            # Park the event in ONBOARDING so the poller never starts baseline
            # while history/batch work is still running.
            monitored = monitor.state.arm_event(
                event,
                first_print=False,
                workflow_mode=WorkflowMode.ONBOARD.value,
                initial_state=EventState.ONBOARDING,
            )
            result = run_onboard(
                repo_root=config.repo_root,
                ticker=ticker,
                fiscal_period=args.period.upper(),
                report_at=report_at,
                dry_run=bool(args.onboard_dry_run),
                force_mode="onboard",
                configured_tickers=config.tickers,
            )
            onboard_payload = result.to_dict()
            if result.status == "first_print_fallback":
                workflow_mode = WorkflowMode.FIRST_PRINT.value
                initial_state = EventState.SCHEDULED
                monitored = monitor.state.arm_event(
                    event,
                    first_print=True,
                    workflow_mode=workflow_mode,
                    initial_state=initial_state,
                )
                monitored.last_error = result.error
                monitor.state.upsert_event(monitored)
            elif result.status in {"onboarding_blocked", "failed"}:
                workflow_mode = WorkflowMode.ONBOARD.value
                monitored.workflow_mode = workflow_mode
                monitored.transition(
                    EventState.ONBOARDING_BLOCKED, error=result.error
                )
                monitor.state.upsert_event(monitored)
            else:
                workflow_mode = WorkflowMode.ONBOARD.value
                monitored.workflow_mode = workflow_mode
                monitored.transition(EventState.SCHEDULED)
                monitored.last_error = None
                monitor.state.upsert_event(monitored)
        else:
            monitored = monitor.state.arm_event(
                event,
                first_print=bool(args.first_print),
                workflow_mode=workflow_mode,
                initial_state=initial_state,
            )
        event = monitored.event
        print(
            json.dumps(
                {
                    "event_id": event.provider_event_id,
                    "ticker": event.ticker,
                    "period": event.fiscal_period,
                    "report_at": event.report_at.isoformat(),
                    "call_at": event.call_at.isoformat(),
                    "state": monitored.state.value,
                    "first_print": monitored.first_print,
                    "workflow_mode": monitored.workflow_mode,
                    "onboard": onboard_payload,
                },
                sort_keys=True,
                default=str,
            )
        )
        if onboard_payload and onboard_payload.get("status") in {
            "onboarding_blocked",
            "failed",
        }:
            return 2
        if onboard_payload and onboard_payload.get("status") == "first_print_fallback":
            return 3
        return 0
    workflow = monitor.workflow
    diagnostics = run_startup_diagnostics(
        config,
        provider_check=lambda: (
            (
                config.inbox_path.is_dir()
                and (
                    config.provider != "watched"
                    or (
                        config.event_manifest_path is not None
                        and config.event_manifest_path.is_dir()
                    )
                )
            ),
            (
                f"inbox={config.inbox_path}; "
                f"event_manifests={config.event_manifest_path}"
                if config.provider == "watched"
                else str(config.inbox_path)
            ),
        ),
        freshness_check=getattr(monitor.freshness, "available", None),
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
    for check in diagnostics:
        if not check.ok:
            logging.warning("%s: %s", check.name, check.detail)
    if args.command == "once":
        print(json.dumps(monitor.run_cycle(), sort_keys=True))
        return 0
    interval = args.interval or config.poll_interval_seconds
    if interval < 1:
        parser.error("--interval must be positive")
    try:
        while True:
            if args.command == "worker":
                processed = monitor.run_next_job()
                if processed:
                    logging.info("processed one workflow job")
                    continue
                time.sleep(interval)
            else:
                logging.info(
                    "cycle=%s", monitor.run_cycle(process_jobs=False)
                )
                time.sleep(interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
