"""Onboard mode orchestrator — pull history, scaffold profile, score, hand off."""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import yaml

from .mode_router import ModeDecision, choose_lookback_years, classify_workflow_mode

LOG = logging.getLogger(__name__)

_PERIOD_RE = re.compile(r"^FY(\d{4})-Q([1-4])$", re.IGNORECASE)
OVERLAY_DIRNAME = "config/company_overlays"


class OnboardError(RuntimeError):
    """Hard failure during onboarding (e.g. missing estpermid)."""


class OnboardBlocked(OnboardError):
    """Onboarding did not finish before report_at; baseline must not proceed."""


@dataclass
class OnboardResult:
    ticker: str
    fiscal_period: str
    mode: str
    status: str
    lookback_years: int | None = None
    reason: str = ""
    prior_event_count: int = 0
    transcripts_pulled: int = 0
    prior_quarters: list[str] = field(default_factory=list)
    output_quarters: list[str] = field(default_factory=list)
    estpermid: int | None = None
    fiscal_calendar_written: bool = False
    history_import_note: str = ""
    allowlist_guidance: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _period_sort_key(period: str) -> tuple[int, int, str]:
    match = _PERIOD_RE.match(str(period))
    if not match:
        return (9999, 9, str(period))
    return (int(match.group(1)), int(match.group(2)), str(period))


def scaffold_quarters_from_periods(
    periods: Sequence[str],
    *,
    target_period: str | None = None,
) -> tuple[list[str], list[str]]:
    """Earliest transcript → prior_quarters; remaining (+ target) → output_quarters."""
    normalized = sorted(
        {str(p).strip().upper() for p in periods if _PERIOD_RE.match(str(p).strip())},
        key=_period_sort_key,
    )
    target = str(target_period).strip().upper() if target_period else None
    if target and _PERIOD_RE.match(target) and target not in normalized:
        normalized.append(target)
        normalized.sort(key=_period_sort_key)
    if not normalized:
        if target and _PERIOD_RE.match(target):
            return [], [target]
        return [], []
    if len(normalized) == 1:
        # Single historical print: treat as prior-only baseline unless it *is* the target.
        only = normalized[0]
        if target and only == target:
            return [], [only]
        return [only], [target] if target and target != only else []
    prior = [normalized[0]]
    output = list(normalized[1:])
    if target and target not in output and target not in prior:
        output.append(target)
        output.sort(key=_period_sort_key)
    return prior, output


def discover_on_disk_periods(repo_root: Path, ticker: str) -> list[str]:
    sn = repo_root / "Structured Narrative"
    raw = sn / "transcripts_raw"
    periods: set[str] = set()
    ticker_key = ticker.strip().upper()
    if raw.is_dir():
        prefix = f"{ticker_key}_"
        for path in raw.glob(f"{ticker_key}_*.txt"):
            stem = path.stem
            if not stem.upper().startswith(prefix):
                continue
            candidate = stem[len(prefix) :].upper()
            if _PERIOD_RE.match(candidate):
                periods.add(candidate)
        nested = raw / ticker_key
        if nested.is_dir():
            for path in nested.glob("*.txt"):
                candidate = path.stem.upper()
                if _PERIOD_RE.match(candidate):
                    periods.add(candidate)
    # Legacy layout used during Phase 3 onboard: Structured Narrative/{TICKER}/FY….txt
    legacy = sn / ticker_key
    if legacy.is_dir():
        for path in legacy.glob("*.txt"):
            candidate = path.stem.upper()
            if _PERIOD_RE.match(candidate):
                periods.add(candidate)
    return sorted(periods, key=_period_sort_key)


def count_prior_provider_events(
    *,
    ticker: str,
    since: datetime,
    until: datetime,
    event_lister: Callable[[str, datetime, datetime], int] | None = None,
) -> int:
    """Count prior earnings events from an injectable Quartr/ROIC lister."""
    if event_lister is None:
        return 0
    return max(0, int(event_lister(ticker, since, until)))


def _overlay_path(repo_root: Path, ticker: str) -> Path:
    return repo_root / "Structured Narrative" / OVERLAY_DIRNAME / f"{ticker.upper()}.json"


def write_company_overlay(
    repo_root: Path,
    *,
    ticker: str,
    company_name: str,
    prior_quarters: Sequence[str],
    output_quarters: Sequence[str],
    estpermid: int | None,
    isin: str | None,
    barra_id: str | None,
) -> Path:
    path = _overlay_path(repo_root, ticker)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ticker": ticker.upper(),
        "company_name": company_name,
        "estpermid": estpermid,
        "isin": isin,
        "barra_id": barra_id,
        "prior_quarters": list(prior_quarters),
        "output_quarters": list(output_quarters),
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def register_overlay_profile(repo_root: Path, ticker: str) -> Any:
    """Load overlay JSON into company_config.COMPANIES for this process."""
    sn = repo_root / "Structured Narrative"
    if str(sn) not in sys.path:
        sys.path.insert(0, str(sn))
    from company_config import COMPANIES, CompanyProfile  # type: ignore

    path = _overlay_path(repo_root, ticker)
    if not path.is_file():
        raise OnboardError(f"Missing company overlay: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    profile = CompanyProfile(
        ticker=str(data["ticker"]).upper(),
        company_name=str(data.get("company_name") or data["ticker"]),
        estpermid=int(data["estpermid"]) if data.get("estpermid") is not None else None,
        isin=data.get("isin") or None,
        barra_id=data.get("barra_id") or None,
        prior_quarters=tuple(data.get("prior_quarters") or ()),
        output_quarters=tuple(data.get("output_quarters") or ()),
    )
    COMPANIES[profile.ticker] = profile
    return profile


def ensure_fiscal_calendar_entry(
    calendars_path: Path,
    ticker: str,
    *,
    calendar_type: str,
    fye_month: int | None = None,
    fye_day: int | None = None,
) -> bool:
    """Write a fiscal_calendars.yaml entry when the ticker is absent. Returns True if written."""
    ticker_key = ticker.strip().upper()
    existing: dict[str, Any] = {}
    if calendars_path.is_file():
        loaded = yaml.safe_load(calendars_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise OnboardError(f"Invalid fiscal calendar YAML: {calendars_path}")
        existing = loaded
        if ticker_key in existing:
            return False

    entry: dict[str, Any]
    ctype = calendar_type.strip().lower()
    if ctype in {"calendar", "calendar_fiscal"}:
        entry = {"type": "calendar_fiscal"}
    elif ctype in {"nvidia", "nvidia_fiscal"}:
        entry = {"type": "nvidia_fiscal"}
    elif ctype in {"offset", "offset_fiscal"}:
        if not fye_month or not fye_day:
            raise OnboardError(
                f"offset_fiscal for {ticker_key} requires fye_month and fye_day"
            )
        entry = {
            "type": "offset_fiscal",
            "fye_month": int(fye_month),
            "fye_day": int(fye_day),
        }
    else:
        # Default safe mapping from EDGAR bootstrap labels.
        entry = {"type": "calendar_fiscal"}

    existing[ticker_key] = entry
    calendars_path.parent.mkdir(parents=True, exist_ok=True)
    calendars_path.write_text(
        yaml.safe_dump(existing, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return True


def allowlist_guidance(ticker: str, configured: Sequence[str]) -> str:
    ticker_key = ticker.strip().upper()
    if ticker_key in {t.strip().upper() for t in configured}:
        return f"{ticker_key} is already in the Roz ticker book."
    current = ",".join(t.strip().upper() for t in configured if t.strip())
    suggested = f"{current},{ticker_key}" if current else ticker_key
    return (
        f"{ticker_key} is integrated into the Roz ticker book during Onboard/"
        f"First-Print (sector file + shared book meta; env "
        f"EARNINGS_MONITOR_TICKERS={suggested} when writable)."
    )


def _run_command(
    argv: Sequence[str],
    *,
    cwd: Path,
    dry_run: bool,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    step = {"argv": list(argv), "cwd": str(cwd), "dry_run": dry_run}
    if dry_run:
        step["returncode"] = 0
        step["skipped"] = "dry_run"
        LOG.info("dry-run: %s", " ".join(argv))
        return step
    LOG.info("running: %s", " ".join(argv))
    completed = subprocess.run(
        list(argv),
        cwd=str(cwd),
        env={**os.environ, **dict(env or {})},
        capture_output=True,
        text=True,
        check=False,
    )
    step["returncode"] = completed.returncode
    step["stdout_tail"] = (completed.stdout or "")[-2000:]
    step["stderr_tail"] = (completed.stderr or "")[-2000:]
    if completed.returncode != 0:
        raise OnboardError(
            f"Command failed ({completed.returncode}): {' '.join(argv)}\n"
            f"{step['stderr_tail'] or step['stdout_tail']}"
        )
    return step


def _resolve_ids(
    repo_root: Path,
    *,
    ticker: str,
    company_name: str,
    prior_quarters: Sequence[str],
    output_quarters: Sequence[str],
    connect: Callable[[], Any] | None,
) -> tuple[int, str | None, str | None]:
    sn = repo_root / "Structured Narrative"
    if str(sn) not in sys.path:
        sys.path.insert(0, str(sn))
    from company_config import CompanyProfile, resolve_company_ids  # type: ignore

    profile = CompanyProfile(
        ticker=ticker.upper(),
        company_name=company_name,
        prior_quarters=tuple(prior_quarters),
        output_quarters=tuple(output_quarters),
    )
    if connect is None:
        try:
            from single_company_extractor import connect as sf_connect  # type: ignore
        except Exception as exc:  # pragma: no cover - import surface
            raise OnboardError(
                f"Cannot import Snowflake connector to resolve estpermid: {exc}"
            ) from exc
        connect = sf_connect

    conn = connect()
    try:
        cur = conn.cursor()
        try:
            resolved = resolve_company_ids(cur, profile)
        finally:
            cur.close()
    finally:
        close = getattr(conn, "close", None)
        if callable(close):
            close()

    if not resolved.estpermid:
        raise OnboardError(
            f"estpermid missing for {ticker.upper()} after Snowflake/LSEG lookup; "
            "refusing to continue Onboard."
        )
    return int(resolved.estpermid), resolved.isin, resolved.barra_id


def _bootstrap_fiscal(
    repo_root: Path,
    ticker: str,
    company_name: str,
) -> tuple[str, int | None, int | None]:
    """Return (calendar_type, fye_month, fye_day) via EDGAR bootstrap when possible."""
    try:
        from src.ingest.edgar.client import EdgarClient
        from src.ingest.edgar.config import load_edgar_config
        from src.ingest.edgar.cik_lookup import resolve_companies_list
        from src.ingest.edgar.fiscal_profile import load_or_bootstrap_fiscal_profile
    except Exception as exc:  # pragma: no cover
        LOG.warning("EDGAR fiscal bootstrap unavailable: %s", exc)
        return "calendar_fiscal", None, None

    cfg = load_edgar_config()
    client = EdgarClient(cfg)
    companies = resolve_companies_list([ticker], client=client)
    if not companies:
        return "calendar_fiscal", None, None
    company = companies[0]
    cik = str(company.get("cik") or company.get("CIK") or "")
    if not cik:
        return "calendar_fiscal", None, None
    submissions = client.fetch_submissions(cik)
    profile = load_or_bootstrap_fiscal_profile(
        ticker,
        company_name or company.get("title") or ticker,
        submissions,
        client=client,
    )
    return profile.calendar_type, profile.fye_month, profile.fye_day


def run_onboard(
    *,
    repo_root: Path,
    ticker: str,
    fiscal_period: str,
    report_at: datetime,
    company_name: str | None = None,
    now: datetime | None = None,
    dry_run: bool = False,
    skip_pull: bool = False,
    skip_ids: bool = False,
    skip_fiscal: bool = False,
    skip_quant: bool = False,
    skip_llm: bool = False,
    skip_panel: bool = False,
    force_mode: str | None = None,
    prior_event_count: int | None = None,
    event_lister: Callable[[str, datetime, datetime], int] | None = None,
    connect: Callable[[], Any] | None = None,
    configured_tickers: Sequence[str] = (),
    run_command: Callable[..., dict[str, Any]] | None = None,
) -> OnboardResult:
    """Execute the Onboard flow. Never silently falls through to baseline on failure."""
    ticker_key = ticker.strip().upper()
    period = fiscal_period.strip().upper()
    current = now or datetime.now(timezone.utc)
    if report_at.tzinfo is None:
        raise OnboardError("report_at must be timezone-aware")
    name = company_name or ticker_key
    runner = run_command or _run_command
    sn = repo_root / "Structured Narrative"
    py = sys.executable

    lookback_years = choose_lookback_years(report_at, now=current)
    since = current - timedelta(days=lookback_years * 365 + 2)
    if prior_event_count is None:
        prior_event_count = count_prior_provider_events(
            ticker=ticker_key,
            since=since,
            until=report_at,
            event_lister=event_lister,
        )
    on_disk = discover_on_disk_periods(repo_root, ticker_key)

    in_registry = False
    has_scored = False
    try:
        if str(sn) not in sys.path:
            sys.path.insert(0, str(sn))
        from company_config import COMPANIES  # type: ignore

        in_registry = ticker_key in COMPANIES or _overlay_path(repo_root, ticker_key).is_file()
        panel = sn / "output" / ticker_key / "parquet" / "feature_panel.parquet"
        panel_csv = sn / "output" / ticker_key / "csv" / "feature_panel.csv"
        has_scored = panel.is_file() or panel_csv.is_file()
    except Exception:
        in_registry = _overlay_path(repo_root, ticker_key).is_file()

    decision: ModeDecision = classify_workflow_mode(
        prior_event_count=prior_event_count,
        on_disk_transcript_count=len(on_disk),
        in_company_registry=in_registry,
        has_scored_history=has_scored,
        report_at=report_at,
        now=current,
    )
    if force_mode:
        decision = ModeDecision(
            mode=force_mode,  # type: ignore[arg-type]
            reason=f"Forced mode={force_mode}",
            lookback_years=lookback_years,
            prior_event_count=prior_event_count,
            on_disk_transcript_count=len(on_disk),
        )

    result = OnboardResult(
        ticker=ticker_key,
        fiscal_period=period,
        mode=decision.mode,
        status="started",
        lookback_years=lookback_years,
        reason=decision.reason,
        prior_event_count=prior_event_count,
        allowlist_guidance=allowlist_guidance(ticker_key, configured_tickers),
    )

    # First-Print fallthrough and full Onboard both integrate the ticker into
    # the shared Roz book (sector file + optional env) so research-regen sees it.
    try:
        from .config import MonitorConfig
        from .ticker_book import ensure_ticker_in_book

        seed = tuple(
            dict.fromkeys(
                str(t).strip().upper()
                for t in (configured_tickers or ())
                if str(t).strip()
            )
        )
        book_config = MonitorConfig(
            repo_root=Path(repo_root),
            database_path=Path(repo_root)
            / "services"
            / "earnings_monitor"
            / "state"
            / "monitor.sqlite3",
            inbox_path=Path(repo_root)
            / "earnings-scraper-main"
            / "earnings-scraper-main"
            / "inbox",
            tickers=seed or ("AAPL",),
            research_sector="xlk_tech",
        )
        integration = ensure_ticker_in_book(
            ticker=ticker_key,
            config=book_config,
            seed_tickers=seed,
        )
        result.steps.append(
            {
                "step": "ticker_book",
                "added": integration.added,
                "tickers": list(integration.tickers),
                "sector_updated": integration.sector_updated,
                "env_updated": integration.env_updated,
            }
        )
        result.allowlist_guidance = allowlist_guidance(
            ticker_key, integration.tickers
        )
    except Exception as exc:  # noqa: BLE001 — book sync must not abort onboard
        result.steps.append(
            {"step": "ticker_book", "error": str(exc), "ticker": ticker_key}
        )
        LOG.warning("Roz ticker book integration failed for %s: %s", ticker_key, exc)

    if decision.mode == "first_print":
        result.status = "first_print_fallback"
        result.error = (
            "FIRST-PRINT FALLTHROUGH: zero prior Quartr/ROIC events and no on-disk "
            "transcripts. Do not run Onboard baseline. Use:\n"
            f"  python -m services.earnings_monitor arm --ticker {ticker_key} "
            f"--period {period} --report-at <iso> --call-at <iso> --first-print"
        )
        result.steps.append({"step": "classify", "mode": "first_print", "reason": decision.reason})
        return result

    if decision.mode == "standard" and not force_mode:
        result.status = "already_standard"
        result.reason = decision.reason
        result.steps.append({"step": "classify", "mode": "standard"})
        return result

    def _deadline_guard(step_name: str) -> None:
        # Use wall clock for real runs; injected `now` stays fixed for tests.
        check_at = current if now is not None else datetime.now(timezone.utc)
        if check_at >= report_at.astimezone(timezone.utc):
            raise OnboardBlocked(
                f"Onboarding blocked at step '{step_name}': report_at "
                f"{report_at.isoformat()} has been reached before Batch/history "
                "completed. Event must remain in onboarding_blocked — never silent "
                "baseline failure."
            )

    try:
        result.steps.append(
            {
                "step": "classify",
                "mode": decision.mode,
                "lookback_years": lookback_years,
                "reason": decision.reason,
            }
        )
        _deadline_guard("classify")

        # ---- Pull transcripts ----
        if not skip_pull:
            _deadline_guard("pull_transcripts")
            if lookback_years >= 10:
                start = report_at - timedelta(days=lookback_years * 365 + 2)
                step = runner(
                    [
                        py,
                        str(sn / "quartr_history_import.py"),
                        "--ticker",
                        ticker_key,
                        "--start",
                        start.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "--end",
                        report_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "--layout",
                        "flat",
                        "--json",
                    ],
                    cwd=repo_root,
                    dry_run=dry_run,
                )
                step["step"] = "quartr_history_import"
                result.steps.append(step)
            else:
                fetch_script = (
                    repo_root
                    / "earnings-scraper-main"
                    / "earnings-scraper-main"
                    / "scripts"
                    / "fetch_transcripts.py"
                )
                if fetch_script.is_file():
                    step = runner(
                        [py, str(fetch_script), ticker_key, "--all", "--no-fallback"],
                        cwd=fetch_script.parent.parent,
                        dry_run=dry_run,
                    )
                    step["step"] = "roic_fetch_transcripts"
                    result.steps.append(step)
                step = runner(
                    [
                        py,
                        str(sn / "export_inbox_to_transcripts_raw.py"),
                        "--ticker",
                        ticker_key,
                    ],
                    cwd=repo_root,
                    dry_run=dry_run,
                )
                step["step"] = "export_inbox_to_transcripts_raw"
                result.steps.append(step)

        on_disk = discover_on_disk_periods(repo_root, ticker_key)
        result.transcripts_pulled = len(on_disk)
        prior_q, output_q = scaffold_quarters_from_periods(on_disk, target_period=period)
        result.prior_quarters = prior_q
        result.output_quarters = output_q
        result.steps.append(
            {
                "step": "scaffold_quarters",
                "prior_quarters": prior_q,
                "output_quarters": output_q,
                "on_disk": on_disk,
            }
        )

        # ---- IDs ----
        estpermid: int | None = None
        isin: str | None = None
        barra_id: str | None = None
        if skip_ids or dry_run:
            estpermid = 0 if dry_run else None
            result.steps.append({"step": "resolve_ids", "skipped": True})
        else:
            _deadline_guard("resolve_ids")
            estpermid, isin, barra_id = _resolve_ids(
                repo_root,
                ticker=ticker_key,
                company_name=name,
                prior_quarters=prior_q,
                output_quarters=output_q,
                connect=connect,
            )
            result.estpermid = estpermid
            result.steps.append(
                {
                    "step": "resolve_ids",
                    "estpermid": estpermid,
                    "isin": isin,
                    "barra_id": barra_id,
                }
            )

        if not dry_run and not skip_ids and not estpermid:
            raise OnboardError(f"estpermid missing for {ticker_key}")

        overlay = write_company_overlay(
            repo_root,
            ticker=ticker_key,
            company_name=name,
            prior_quarters=prior_q,
            output_quarters=output_q,
            estpermid=None if dry_run and not estpermid else estpermid,
            isin=isin,
            barra_id=barra_id,
        )
        if not dry_run:
            register_overlay_profile(repo_root, ticker_key)
        result.steps.append({"step": "write_overlay", "path": str(overlay)})

        # ---- Fiscal calendar ----
        if not skip_fiscal:
            _deadline_guard("fiscal_calendar")
            calendars = repo_root / "config" / "fiscal_calendars.yaml"
            if dry_run:
                result.steps.append({"step": "fiscal_calendar", "skipped": "dry_run"})
            else:
                cal_type, fye_month, fye_day = _bootstrap_fiscal(repo_root, ticker_key, name)
                wrote = ensure_fiscal_calendar_entry(
                    calendars,
                    ticker_key,
                    calendar_type=cal_type,
                    fye_month=fye_month,
                    fye_day=fye_day,
                )
                result.fiscal_calendar_written = wrote
                result.steps.append(
                    {
                        "step": "fiscal_calendar",
                        "written": wrote,
                        "calendar_type": cal_type,
                        "fye_month": fye_month,
                        "fye_day": fye_day,
                    }
                )

        # ---- Quant ----
        if not skip_quant:
            _deadline_guard("quant")
            step = runner(
                [py, str(sn / "single_company_extractor.py"), "--ticker", ticker_key],
                cwd=repo_root,
                dry_run=dry_run,
            )
            step["step"] = "single_company_extractor"
            result.steps.append(step)
            step = runner(
                [py, str(sn / "narrative_zscore.py"), "--ticker", ticker_key],
                cwd=repo_root,
                dry_run=dry_run,
            )
            step["step"] = "narrative_zscore"
            result.steps.append(step)

        # ---- Batch LLM ----
        if not skip_llm:
            _deadline_guard("batch_llm")
            batch = sn / "run_universe_batch.py"
            if batch.is_file():
                step = runner(
                    [
                        py,
                        str(batch),
                        "--tickers",
                        ticker_key,
                        "--force",
                    ],
                    cwd=repo_root,
                    dry_run=dry_run,
                )
                step["step"] = "run_universe_batch"
                result.steps.append(step)
            else:
                step = runner(
                    [
                        py,
                        str(sn / "run_company_pipeline.py"),
                        "--ticker",
                        ticker_key,
                        "--batch",
                        "--skip-quant",
                    ],
                    cwd=repo_root,
                    dry_run=dry_run,
                )
                step["step"] = "run_company_pipeline_batch"
                result.steps.append(step)

        # ---- Panel + history_import handoff ----
        if not skip_panel:
            _deadline_guard("feature_panel")
            step = runner(
                [
                    py,
                    str(sn / "build_feature_panel.py"),
                    "--ticker",
                    ticker_key,
                    "--from-registry",
                ],
                cwd=repo_root,
                dry_run=dry_run,
            )
            step["step"] = "build_feature_panel"
            result.steps.append(step)
            result.history_import_note = (
                "Handoff: refresh the monitor dataset with history_import after panel build:\n"
                f"  python -m services.earnings_monitor.history_import "
                f"--source-root \"{repo_root}\" --tickers {ticker_key}"
            )
            result.steps.append(
                {
                    "step": "history_import_handoff",
                    "note": result.history_import_note,
                }
            )

        _deadline_guard("complete")
        result.status = "completed"
        return result
    except OnboardBlocked as exc:
        result.status = "onboarding_blocked"
        result.error = str(exc)
        result.steps.append({"step": "blocked", "error": str(exc)})
        return result
    except OnboardError as exc:
        result.status = "failed"
        result.error = str(exc)
        result.steps.append({"step": "failed", "error": str(exc)})
        return result
