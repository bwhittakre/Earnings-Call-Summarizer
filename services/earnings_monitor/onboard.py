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


class ProviderHistoryUnavailable(OnboardError):
    """Prior Quartr/ROIC event history could not be counted for mode classification."""


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


def _ensure_structured_narrative_path(repo_root: Path) -> Path:
    sn = Path(repo_root) / "Structured Narrative"
    sn_str = str(sn)
    if sn_str not in sys.path:
        sys.path.insert(0, sn_str)
    return sn


def _parse_provider_event_at(row: Mapping[str, Any]) -> datetime | None:
    raw = row.get("date") or row.get("scheduled_at") or row.get("call_at")
    if not isinstance(raw, (str, datetime)):
        return None
    parsed = raw if isinstance(raw, datetime) else datetime.fromisoformat(
        str(raw).replace("Z", "+00:00")
    )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def make_quartr_event_lister(
    repo_root: Path | None = None,
    *,
    client: Any | None = None,
    api_key: str | None = None,
) -> Callable[[str, datetime, datetime], int]:
    """Build a Quartr-backed ``(ticker, since, until) -> count`` event lister.

    Counts events in ``[since, until)`` that normalize to a fiscal period
    (earnings-like rows). Raises ``ProviderHistoryUnavailable`` when the API
    key is missing or Quartr cannot resolve/list the company.
    """

    def _count(ticker: str, since: datetime, until: datetime) -> int:
        try:
            if repo_root is not None:
                _ensure_structured_narrative_path(repo_root)
            from quartr_history_import import (  # type: ignore
                QuartrApiClient,
                normalize_fiscal_period,
            )
        except ImportError as exc:  # pragma: no cover - packaging/env issue
            raise ProviderHistoryUnavailable(
                "quartr_history_import is unavailable; cannot count prior "
                f"provider events ({exc})"
            ) from exc

        try:
            api = client or QuartrApiClient(api_key=api_key)
            if not getattr(api, "api_key", None) and client is None:
                raise ProviderHistoryUnavailable(
                    "QUARTR_API_KEY is not set; cannot count prior provider "
                    "events for mode classification. Export QUARTR_API_KEY, "
                    "pass event_lister=/prior_event_count=, or use "
                    "arm --first-print for true first prints."
                )
            company_id = api.resolve_company_id(ticker)
            rows = api.iter_events(company_id=company_id, start=since, end=until)
        except ProviderHistoryUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001 — surface provider failures clearly
            raise ProviderHistoryUnavailable(
                f"Quartr prior-event lookup failed for {ticker.strip().upper()}: {exc}"
            ) from exc

        until_utc = until if until.tzinfo else until.replace(tzinfo=timezone.utc)
        until_utc = until_utc.astimezone(timezone.utc)
        count = 0
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            period = normalize_fiscal_period(
                fiscal_year=row.get("fiscalYear"),
                fiscal_period=row.get("fiscalPeriod") or row.get("fiscal_period"),
                title=str(row.get("title") or ""),
            )
            if not period:
                continue
            event_at = _parse_provider_event_at(row)
            if event_at is not None and event_at >= until_utc:
                continue
            count += 1
        return count

    return _count


def count_prior_provider_events(
    *,
    ticker: str,
    since: datetime,
    until: datetime,
    event_lister: Callable[[str, datetime, datetime], int] | None = None,
) -> int:
    """Count prior earnings events from an injectable Quartr/ROIC lister.

    ``event_lister`` is required — callers must pass a lister (see
    ``make_quartr_event_lister``) or supply ``prior_event_count`` to
    ``run_onboard`` instead. Silent ``0`` when unwired is intentionally not
    supported (it mis-classifies names with real provider history as First-Print).
    """
    if event_lister is None:
        raise ProviderHistoryUnavailable(
            "event_lister is required to count prior provider events. "
            "Wire make_quartr_event_lister(), pass event_lister=, or set "
            "prior_event_count= explicitly. For true first prints use "
            "arm --first-print."
        )
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
    from company_config import get_company  # type: ignore

    path = _overlay_path(repo_root, ticker)
    if not path.is_file():
        raise OnboardError(f"Missing company overlay: {path}")
    # get_company prefers on-disk overlays and caches into COMPANIES.
    return get_company(ticker, overlay_dir=path.parent)


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


def _read_overlay_ids(
    repo_root: Path, ticker: str
) -> tuple[int | None, str | None, str | None]:
    path = _overlay_path(repo_root, ticker)
    if not path.is_file():
        return None, None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None, None
    est = data.get("estpermid")
    isin = data.get("isin") or None
    barra = data.get("barra_id") or None
    try:
        est_i = int(est) if est is not None else None
    except (TypeError, ValueError):
        est_i = None
    return est_i, (str(isin) if isin else None), (str(barra) if barra else None)


def _resolve_ids(
    repo_root: Path,
    *,
    ticker: str,
    company_name: str,
    prior_quarters: Sequence[str],
    output_quarters: Sequence[str],
    connect: Callable[[], Any] | None,
    isin: str | None = None,
    estpermid: int | None = None,
    barra_id: str | None = None,
    refresh_ids: bool = False,
) -> tuple[int, str | None, str | None, str]:
    """Resolve ESTPERMID / ISIN / BARRA_ID.

    Returns ``(estpermid, isin, barra_id, source)`` where source is one of
    ``override``, ``overlay``, or ``snowflake``.
    """
    ticker_key = ticker.strip().upper()
    isin_key = (isin or "").strip().upper() or None
    barra_key = (barra_id or "").strip() or None

    if estpermid is not None and int(estpermid) > 0:
        return int(estpermid), isin_key, barra_key, "override"

    if not refresh_ids:
        ov_est, ov_isin, ov_barra = _read_overlay_ids(repo_root, ticker_key)
        if ov_est:
            return (
                ov_est,
                isin_key or ov_isin,
                barra_key or ov_barra,
                "overlay",
            )

    sn = repo_root / "Structured Narrative"
    if str(sn) not in sys.path:
        sys.path.insert(0, str(sn))
    from company_config import CompanyProfile, resolve_company_ids  # type: ignore

    profile = CompanyProfile(
        ticker=ticker_key,
        company_name=company_name,
        isin=isin_key,
        barra_id=barra_key,
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
        hint = (
            f" Pass --isin <ISIN> (recommended; IBESTICKER can be recycled, e.g. STRW) "
            f"or --estpermid / --barra-id overrides."
            if not isin_key
            else " Check LSEG/MSCI share access for this ISIN."
        )
        raise OnboardError(
            f"estpermid missing for {ticker_key} after Snowflake/LSEG lookup; "
            f"refusing to continue Onboard.{hint}"
        )
    return (
        int(resolved.estpermid),
        resolved.isin or isin_key,
        resolved.barra_id or barra_key,
        "snowflake",
    )


def _bootstrap_fiscal(
    repo_root: Path,
    ticker: str,
    company_name: str,
) -> tuple[str, int | None, int | None]:
    """Return (calendar_type, fye_month, fye_day) via EDGAR bootstrap when possible."""
    try:
        from src.ingest.edgar.client import EdgarClient, make_json_fetcher
        from src.ingest.edgar.config import load_edgar_config
        from src.ingest.edgar.cik_lookup import resolve_companies_list
        from src.ingest.edgar.fiscal_profile import load_or_bootstrap_fiscal_profile
    except Exception as exc:  # pragma: no cover
        LOG.warning("EDGAR fiscal bootstrap unavailable: %s", exc)
        return "calendar_fiscal", None, None

    try:
        cfg = load_edgar_config()
        client = EdgarClient(cfg)
        companies = resolve_companies_list(ticker, fetcher=make_json_fetcher(client))
        if not companies:
            return "calendar_fiscal", None, None
        ticker_key, cik, title = companies[0]
        if not cik:
            return "calendar_fiscal", None, None
        submissions = client.fetch_submissions(int(cik))
        profile = load_or_bootstrap_fiscal_profile(
            ticker_key,
            company_name or title or ticker,
            submissions,
            client=client,
        )
        return profile.calendar_type, profile.fye_month, profile.fye_day
    except Exception as exc:  # noqa: BLE001 — fiscal is best-effort
        LOG.warning("EDGAR fiscal bootstrap failed for %s: %s", ticker, exc)
        return "calendar_fiscal", None, None


def _monitor_paths(repo_root: Path) -> tuple[Path, Path]:
    """Resolve operational DB and history dataset paths (env-aware)."""
    db = Path(
        os.environ.get(
            "EARNINGS_MONITOR_DB",
            str(
                Path(repo_root)
                / "services"
                / "earnings_monitor"
                / "state"
                / "monitor.sqlite3"
            ),
        )
    )
    dataset = Path(
        os.environ.get(
            "EARNINGS_MONITOR_DATASET",
            str(
                Path(repo_root)
                / "data"
                / "earnings_monitor"
                / "company_quarters.parquet"
            ),
        )
    )
    return db, dataset


def sync_book_after_onboard(
    *,
    repo_root: Path,
    ticker: str,
    fiscal_period: str,
    configured_tickers: Sequence[str] = (),
    dry_run: bool = False,
    import_history_fn: Callable[..., Any] | None = None,
) -> list[dict[str, Any]]:
    """Wire sector/env/SQLite book, refresh history parquet, mark research dirty.

    History import writes the full book (not just *ticker*): ``import_history``
    overwrites the destination dataset, so a single-ticker import would wipe peers.
    Failures are recorded as steps and never raised to the caller.
    """
    from .config import MonitorConfig
    from .history_import import import_history
    from .state import OperationalState
    from .ticker_book import ensure_ticker_in_book

    ticker_key = ticker.strip().upper()
    period = fiscal_period.strip().upper()
    steps: list[dict[str, Any]] = []
    seed = tuple(
        dict.fromkeys(
            str(t).strip().upper()
            for t in (configured_tickers or ())
            if str(t).strip()
        )
    )
    db_path, dataset_path = _monitor_paths(repo_root)
    book_config = MonitorConfig(
        repo_root=Path(repo_root),
        database_path=db_path,
        inbox_path=Path(repo_root)
        / "earnings-scraper-main"
        / "earnings-scraper-main"
        / "inbox",
        tickers=seed or (ticker_key,),
        research_sector="xlk_tech",
    )
    book_tickers: tuple[str, ...] = seed or (ticker_key,)

    if dry_run:
        steps.append(
            {
                "step": "book_sync",
                "dry_run": True,
                "ticker": ticker_key,
                "dataset": str(dataset_path),
            }
        )
        return steps

    try:
        state = OperationalState(db_path)
        state.initialize()
        integration = ensure_ticker_in_book(
            ticker=ticker_key,
            config=book_config,
            state=state,
            seed_tickers=seed,
        )
        book_tickers = integration.tickers
        steps.append(
            {
                "step": "book_sync",
                "added": integration.added,
                "tickers": list(integration.tickers),
                "sector_updated": integration.sector_updated,
                "env_updated": integration.env_updated,
                "meta_updated": integration.meta_updated,
            }
        )
    except Exception as exc:  # noqa: BLE001
        steps.append({"step": "book_sync", "error": str(exc), "ticker": ticker_key})
        LOG.warning("Post-onboard book sync failed for %s: %s", ticker_key, exc)
        state = None

    importer = import_history_fn or import_history
    try:
        hist = importer(
            repo_root,
            dataset_path,
            tickers=book_tickers,
        )
        steps.append(
            {
                "step": "history_import",
                "records": getattr(hist, "records", None),
                "tickers": list(getattr(hist, "tickers", book_tickers)),
                "missing_tickers": list(getattr(hist, "missing_tickers", ()) or ()),
                "destination": str(dataset_path),
            }
        )
    except Exception as exc:  # noqa: BLE001
        steps.append(
            {
                "step": "history_import",
                "error": str(exc),
                "tickers": list(book_tickers),
                "destination": str(dataset_path),
            }
        )
        LOG.warning("Post-onboard history_import failed for %s: %s", ticker_key, exc)

    if state is not None:
        try:
            dirty = state.mark_research_book_dirty(
                reason="onboard",
                trigger=f"{ticker_key}:{period}",
            )
            steps.append(
                {
                    "step": "research_dirty",
                    "reason": dirty.get("reason"),
                    "triggers": list(dirty.get("triggers") or []),
                }
            )
        except Exception as exc:  # noqa: BLE001
            steps.append({"step": "research_dirty", "error": str(exc)})
            LOG.warning(
                "Post-onboard research dirty mark failed for %s: %s", ticker_key, exc
            )
    else:
        steps.append(
            {
                "step": "research_dirty",
                "error": "skipped: operational state unavailable",
            }
        )

    return steps


def _pull_history_transcripts(
    *,
    repo_root: Path,
    ticker: str,
    report_at: datetime,
    lookback_years: int,
    dry_run: bool,
    run_command: Callable[..., dict[str, Any]],
    allow_roic_fallback: bool = False,
) -> list[dict[str, Any]]:
    """Accept lookback transcripts already in ``transcripts_raw`` (Quartr MCP).

    Default path is MCP-only: Cursor Quartr MCP → flat
    ``transcripts_raw/{TICKER}_FY….txt`` for ``LocalFileProvider``. Neither
    Quartr REST (``quartr_history_import``) nor ROIC runs automatically.

    Pass ``allow_roic_fallback=True`` (CLI ``--allow-roic-fallback``) only when
    an explicit ROIC fetch + inbox export is required. Use ``--skip-pull`` when
    the agent has already written the MCP files.
    """
    del report_at  # window sizing is an agent/MCP concern; disk is source of truth
    ticker_key = ticker.strip().upper()
    sn = repo_root / "Structured Narrative"
    py = sys.executable
    steps: list[dict[str, Any]] = []
    on_disk = discover_on_disk_periods(repo_root, ticker_key)
    steps.append(
        {
            "step": "quartr_mcp_seed",
            "lookback_years": lookback_years,
            "on_disk": on_disk,
            "note": (
                "Default: Quartr MCP → transcripts_raw/{TICKER}_FY….txt "
                "(LocalFileProvider). Quartr REST and ROIC are not used unless "
                "explicitly opted in."
            ),
        }
    )
    if dry_run:
        steps.append(
            {
                "step": "roic_fallback",
                "skipped": "dry_run",
                "allow_roic_fallback": allow_roic_fallback,
                "note": (
                    "ROIC is opt-in via --allow-roic-fallback when "
                    "transcripts_raw is empty"
                ),
            }
        )
        return steps

    if on_disk:
        return steps

    if not allow_roic_fallback:
        raise OnboardError(
            f"No transcripts on disk for {ticker_key}. Seed via Quartr MCP into "
            f"Structured Narrative/transcripts_raw/{ticker_key}_FY….txt "
            f"(LocalFileProvider layout), then re-run onboard "
            f"(optionally with --skip-pull). "
            f"ROIC is not tried by default; pass --allow-roic-fallback only if "
            f"you intentionally want the ROIC inbox path. "
            f"Quartr REST (quartr_history_import) is never used here."
        )

    fetch_script = (
        repo_root
        / "earnings-scraper-main"
        / "earnings-scraper-main"
        / "scripts"
        / "fetch_transcripts.py"
    )
    if fetch_script.is_file():
        try:
            step = run_command(
                [py, str(fetch_script), ticker_key, "--all", "--no-fallback"],
                cwd=fetch_script.parent.parent,
                dry_run=False,
            )
            step["step"] = "roic_fetch_transcripts"
            step["fallback_for"] = "quartr_mcp_seed"
            steps.append(step)
        except OnboardError as exc:
            steps.append(
                {
                    "step": "roic_fetch_transcripts",
                    "fallback_for": "quartr_mcp_seed",
                    "error": str(exc),
                }
            )
            LOG.warning("ROIC fallback fetch failed for %s: %s", ticker_key, exc)

    try:
        step = run_command(
            [
                py,
                str(sn / "export_inbox_to_transcripts_raw.py"),
                "--ticker",
                ticker_key,
            ],
            cwd=repo_root,
            dry_run=False,
        )
        step["step"] = "export_inbox_to_transcripts_raw"
        step["fallback_for"] = "quartr_mcp_seed"
        steps.append(step)
    except OnboardError as exc:
        steps.append(
            {
                "step": "export_inbox_to_transcripts_raw",
                "fallback_for": "quartr_mcp_seed",
                "error": str(exc),
            }
        )
        LOG.warning("ROIC inbox export failed for %s: %s", ticker_key, exc)

    on_disk = discover_on_disk_periods(repo_root, ticker_key)
    if not on_disk:
        raise OnboardError(
            f"No transcripts on disk for {ticker_key} after opt-in ROIC fallback. "
            f"Seed via Quartr MCP into "
            f"Structured Narrative/transcripts_raw/{ticker_key}_FY….txt "
            f"and re-run (optionally with --skip-pull)."
        )
    return steps


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
    use_quartr_rest: bool = False,
    allow_roic_fallback: bool = False,
    isin: str | None = None,
    estpermid: int | None = None,
    barra_id: str | None = None,
    refresh_ids: bool = False,
    connect: Callable[[], Any] | None = None,
    configured_tickers: Sequence[str] = (),
    run_command: Callable[..., dict[str, Any]] | None = None,
    import_history_fn: Callable[..., Any] | None = None,
    skip_book_sync: bool = False,
    research_sector: str = "xlk_tech",
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
    history_steps: list[dict[str, Any]] = []
    on_disk = discover_on_disk_periods(repo_root, ticker_key)
    if prior_event_count is None:
        lister = event_lister
        if lister is None and use_quartr_rest:
            lister = make_quartr_event_lister(repo_root)
        if lister is not None:
            try:
                prior_event_count = count_prior_provider_events(
                    ticker=ticker_key,
                    since=since,
                    until=report_at,
                    event_lister=lister,
                )
                history_steps.append(
                    {
                        "step": "count_prior_events",
                        "prior_event_count": prior_event_count,
                        "source": "quartr_rest" if use_quartr_rest else "event_lister",
                        "since": since.isoformat(),
                        "until": report_at.isoformat(),
                    }
                )
            except ProviderHistoryUnavailable as exc:
                if force_mode:
                    LOG.warning(
                        "Prior-event count unavailable for %s under force_mode=%s: %s",
                        ticker_key,
                        force_mode,
                        exc,
                    )
                    prior_event_count = 0
                    history_steps.append(
                        {
                            "step": "count_prior_events",
                            "prior_event_count": 0,
                            "warning": str(exc),
                            "forced": force_mode,
                        }
                    )
                else:
                    result = OnboardResult(
                        ticker=ticker_key,
                        fiscal_period=period,
                        mode="unknown",
                        status="failed",
                        lookback_years=lookback_years,
                        reason="Provider history unavailable for mode classification",
                        prior_event_count=0,
                        allowlist_guidance=allowlist_guidance(
                            ticker_key, configured_tickers
                        ),
                        error=str(exc),
                        steps=[
                            {
                                "step": "count_prior_events",
                                "error": str(exc),
                            }
                        ],
                    )
                    return result
        else:
            # Default: classify from Quartr MCP-seeded transcripts_raw only.
            prior_event_count = len(on_disk)
            history_steps.append(
                {
                    "step": "count_prior_events",
                    "prior_event_count": prior_event_count,
                    "source": "on_disk_mcp",
                    "note": (
                        "Quartr REST is opt-in (--use-quartr-rest). "
                        "Mode uses on-disk MCP transcript count."
                    ),
                }
            )

    in_registry = False
    has_scored = False
    try:
        _ensure_structured_narrative_path(repo_root)
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
        steps=list(history_steps),
    )

    # First-Print fallthrough and full Onboard both integrate the ticker into
    # the shared Roz book (sector file + optional env) so research-regen sees it.
    # New-sector case studies pass skip_book_sync=True so they do not append
    # into the live xlk_tech / SQLite book.
    if skip_book_sync:
        result.steps.append(
            {
                "step": "ticker_book",
                "skipped": True,
                "research_sector": research_sector,
                "note": "skip_book_sync: sector file is managed by the caller",
            }
        )
    else:
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
                research_sector=research_sector,
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
                    "research_sector": research_sector,
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

        # ---- Pull transcripts (MCP default; ROIC only with --allow-roic-fallback) ----
        if not skip_pull:
            _deadline_guard("pull_transcripts")
            pull_steps = _pull_history_transcripts(
                repo_root=repo_root,
                ticker=ticker_key,
                report_at=report_at,
                lookback_years=lookback_years,
                dry_run=dry_run,
                run_command=runner,
                allow_roic_fallback=allow_roic_fallback,
            )
            result.steps.extend(pull_steps)

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
        resolved_est: int | None = None
        resolved_isin: str | None = None
        resolved_barra: str | None = None
        if skip_ids or dry_run:
            resolved_est = (
                0
                if dry_run
                else (int(estpermid) if estpermid is not None else None)
            )
            resolved_isin = (isin or "").strip().upper() or None
            resolved_barra = (barra_id or "").strip() or None
            result.steps.append(
                {
                    "step": "resolve_ids",
                    "skipped": True,
                    "estpermid": resolved_est,
                    "isin": resolved_isin,
                    "barra_id": resolved_barra,
                }
            )
        else:
            _deadline_guard("resolve_ids")
            resolved_est, resolved_isin, resolved_barra, id_source = _resolve_ids(
                repo_root,
                ticker=ticker_key,
                company_name=name,
                prior_quarters=prior_q,
                output_quarters=output_q,
                connect=connect,
                isin=isin,
                estpermid=estpermid,
                barra_id=barra_id,
                refresh_ids=refresh_ids,
            )
            result.estpermid = resolved_est
            result.steps.append(
                {
                    "step": "resolve_ids",
                    "estpermid": resolved_est,
                    "isin": resolved_isin,
                    "barra_id": resolved_barra,
                    "source": id_source,
                }
            )

        if not dry_run and not skip_ids and not resolved_est:
            raise OnboardError(f"estpermid missing for {ticker_key}")

        overlay = write_company_overlay(
            repo_root,
            ticker=ticker_key,
            company_name=name,
            prior_quarters=prior_q,
            output_quarters=output_q,
            estpermid=None if dry_run and not resolved_est else resolved_est,
            isin=resolved_isin,
            barra_id=resolved_barra,
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
                existing_cals = {}
                if calendars.is_file():
                    loaded = yaml.safe_load(calendars.read_text(encoding="utf-8")) or {}
                    if isinstance(loaded, dict):
                        existing_cals = loaded
                if ticker_key in existing_cals:
                    result.fiscal_calendar_written = False
                    result.steps.append(
                        {
                            "step": "fiscal_calendar",
                            "written": False,
                            "skipped": "already_configured",
                        }
                    )
                else:
                    cal_type, fye_month, fye_day = _bootstrap_fiscal(
                        repo_root, ticker_key, name
                    )
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

        # ---- Panel + auto-wire book / history / research dirty ----
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
            if skip_book_sync:
                result.steps.append(
                    {
                        "step": "book_sync",
                        "skipped": True,
                        "research_sector": research_sector,
                    }
                )
                result.history_import_note = (
                    "Book/history sync skipped (skip_book_sync). "
                    "Feature panel is on disk; live Roz book was not rewritten."
                )
                sync_steps = []
            else:
                sync_steps = sync_book_after_onboard(
                    repo_root=repo_root,
                    ticker=ticker_key,
                    fiscal_period=period,
                    configured_tickers=configured_tickers,
                    dry_run=dry_run,
                    import_history_fn=import_history_fn,
                )
                result.steps.extend(sync_steps)
                hist_step = next(
                    (s for s in sync_steps if s.get("step") == "history_import"),
                    None,
                )
                if hist_step and not hist_step.get("error"):
                    result.history_import_note = (
                        f"History dataset refreshed at {hist_step.get('destination')} "
                        f"({hist_step.get('records')} records). Research book marked dirty; "
                        "run research-regen (or wait for the regen loop) for Rank IC / "
                        "consolidated HTML."
                    )
                else:
                    err = (hist_step or {}).get("error") or "history_import not run"
                    result.history_import_note = (
                        f"History import incomplete ({err}). Retry:\n"
                        f"  python -m services.earnings_monitor.history_import "
                        f"--source-root \"{repo_root}\""
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
