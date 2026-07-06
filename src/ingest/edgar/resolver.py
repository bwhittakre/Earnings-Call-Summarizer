from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from src.ingest.edgar.cik_lookup import resolve_companies_list
from src.ingest.edgar.client import EdgarClient, make_json_fetcher
from src.ingest.edgar.config import EdgarConfig, load_edgar_config
from src.ingest.edgar.fiscal_profile import FiscalProfile, load_or_bootstrap_fiscal_profile
from src.ingest.edgar.models import EdgarFetchError, FetchResult, FetchedDocument
from src.ingest.edgar.selector import build_quarter_fetch_plan
from src.ingest.edgar.writer import should_skip_fetch, write_quarter_package
from src.repo_gitignore import sync_filings_gitignore
from src.ingest.filings.fiscal import (
    fiscal_year_prefix,
    is_q4_quarter,
    normalize_quarter_label,
    parse_quarters_list,
    prior_quarter_labels_for_fy_q4,
    quarter_sort_key,
)
from src.ingest.filings.sec_sanitize import sanitize_filing_text
from src.market.fiscal_calendar import DEFAULT_FISCAL_CALENDARS_PATH, load_fiscal_calendars
from src.market.fiscal_resolver import resolve_quarter_end_date
from src.market.quarter_end_mode import QuarterEndRun, build_quarter_end_run
from src.market.quarter_labels import format_quarter_label, parse_quarter_label


@dataclass
class EnsureFetchSummary:
    fetched: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str, str]] = field(default_factory=list)


def next_quarter_label(current: str) -> str:
    is_fiscal, year, quarter_num = parse_quarter_label(current)
    if quarter_num == 4:
        return format_quarter_label(is_fiscal, year + 1, 1)
    return format_quarter_label(is_fiscal, year, quarter_num + 1)


def _quarter_range(from_quarter: str, to_quarter: str) -> list[str]:
    start = parse_quarters_list(from_quarter)[0]
    end = parse_quarters_list(to_quarter)[0]
    if quarter_sort_key(start) > quarter_sort_key(end):
        raise EdgarFetchError(f"--from {start} must be on or before --to {end}.")

    quarters: list[str] = []
    cursor = start
    while quarter_sort_key(cursor) <= quarter_sort_key(end):
        quarters.append(cursor)
        if cursor == end:
            break
        cursor = next_quarter_label(cursor)
    return quarters


def _yaml_tickers(calendars_path: Path) -> set[str]:
    try:
        return set(load_fiscal_calendars(calendars_path))
    except Exception:
        return set()


def _fiscal_profile_for_fetch(
    ticker_key: str,
    company_name: str,
    submissions: dict,
    *,
    calendars_path: Path,
) -> FiscalProfile | None:
    if ticker_key in _yaml_tickers(calendars_path):
        return None
    return load_or_bootstrap_fiscal_profile(ticker_key, company_name, submissions)


def expand_fetch_quarters(quarter: str) -> list[str]:
    """Return quarters to fetch, prefetching Q1–Q3 siblings when target is Q4 (10-K)."""
    normalized = normalize_quarter_label(quarter)
    if not is_q4_quarter(normalized):
        return [normalized]
    fiscal_year = fiscal_year_prefix(normalized)
    return [*prior_quarter_labels_for_fy_q4(fiscal_year), normalized]


def _record_fetch_result(
    summary: EnsureFetchSummary,
    *,
    label: str,
    result: FetchResult,
    dry_run: bool,
) -> None:
    if dry_run and not result.skipped:
        summary.fetched.append(f"{label} (planned)")
    elif result.skipped:
        summary.skipped.append(label)
    else:
        summary.fetched.append(label)


def _fetch_ticker_quarters(
    *,
    ticker_key: str,
    quarters: list[str],
    filings_root: Path,
    summary: EnsureFetchSummary,
    edgar_client: EdgarClient,
    cfg: EdgarConfig,
    calendars_path: Path,
    overwrite: bool,
    dry_run: bool,
    period_end_override: date | None = None,
    period_end_override_quarter: str | None = None,
) -> None:
    for quarter in quarters:
        label = f"{ticker_key} {quarter}"
        override = (
            period_end_override
            if period_end_override_quarter == quarter
            else None
        )
        result = fetch_quarter_package(
            ticker=ticker_key,
            quarter=quarter,
            filings_root=filings_root,
            overwrite=overwrite,
            dry_run=dry_run,
            client=edgar_client,
            config=cfg,
            calendars_path=calendars_path,
            period_end_override=override,
        )
        _record_fetch_result(summary, label=label, result=result, dry_run=dry_run)


def _anchor_override_for_quarter(
    ticker_key: str,
    quarter: str,
    anchor_date: date,
    *,
    calendars_path: Path,
    tolerance_days: int = 5,
) -> date | None:
    try:
        period_end = resolve_quarter_end_date(
            ticker_key,
            quarter,
            calendars_path=calendars_path,
        )
    except Exception:
        return anchor_date
    if abs((period_end - anchor_date).days) <= tolerance_days:
        return anchor_date
    return None


def plan_quarter_fetch(
    *,
    ticker: str,
    quarter: str,
    filings_root: Path,
    client: EdgarClient | None = None,
    config: EdgarConfig | None = None,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
):
    cfg = config or load_edgar_config()
    edgar_client = client or EdgarClient(cfg)
    fetcher = make_json_fetcher(edgar_client)
    ticker_key, cik, company_name = resolve_companies_list(ticker, fetcher=fetcher)[0]
    submissions = edgar_client.fetch_submissions(cik)
    fiscal_profile = _fiscal_profile_for_fetch(
        ticker_key,
        company_name,
        submissions,
        calendars_path=calendars_path,
    )
    return build_quarter_fetch_plan(
        ticker=ticker_key,
        quarter=quarter,
        filings_root=filings_root,
        config=cfg,
        client=edgar_client,
        submissions=submissions,
        cik=cik,
        fiscal_profile=fiscal_profile,
    )


def resolve_quarter_end_run_for_companies(
    companies: str,
    anchor_date: date,
    *,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    client: EdgarClient | None = None,
) -> QuarterEndRun:
    cfg = load_edgar_config()
    edgar_client = client or EdgarClient(cfg)
    fetcher = make_json_fetcher(edgar_client)
    company_entries = resolve_companies_list(companies, fetcher=fetcher)
    fiscal_profiles: dict[str, FiscalProfile] = {}
    tickers: list[str] = []

    for ticker_key, cik, company_name in company_entries:
        tickers.append(ticker_key)
        if ticker_key not in _yaml_tickers(calendars_path):
            submissions = edgar_client.fetch_submissions(cik)
            fiscal_profiles[ticker_key] = load_or_bootstrap_fiscal_profile(
                ticker_key,
                company_name,
                submissions,
            )

    return build_quarter_end_run(
        tickers,
        anchor_date,
        calendars_path=calendars_path,
        fiscal_profiles=fiscal_profiles,
    )


def fetch_quarter_package(
    *,
    ticker: str,
    quarter: str,
    filings_root: Path,
    overwrite: bool = False,
    dry_run: bool = False,
    client: EdgarClient | None = None,
    config: EdgarConfig | None = None,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
    period_end_override: date | None = None,
) -> FetchResult:
    cfg = config or load_edgar_config()
    edgar_client = client or EdgarClient(cfg)
    fetcher = make_json_fetcher(edgar_client)
    ticker_key, cik, company_name = resolve_companies_list(ticker, fetcher=fetcher)[0]
    submissions = edgar_client.fetch_submissions(cik)
    fiscal_profile = _fiscal_profile_for_fetch(
        ticker_key,
        company_name,
        submissions,
        calendars_path=calendars_path,
    )

    plan = build_quarter_fetch_plan(
        ticker=ticker_key,
        quarter=quarter,
        filings_root=filings_root,
        config=cfg,
        client=edgar_client,
        submissions=submissions,
        cik=cik,
        fiscal_profile=fiscal_profile,
        period_end_override=period_end_override,
    )

    if should_skip_fetch(plan.folder, plan, overwrite=overwrite):
        return FetchResult(plan=plan, skipped=True)

    if dry_run:
        return FetchResult(plan=plan)

    fetched: list[FetchedDocument] = []
    for doc in plan.documents:
        raw = edgar_client.fetch_filing_document(
            cik,
            doc.filing.accession_number,
            doc.filing.primary_document,
        )
        text = sanitize_filing_text(raw)
        if not text.strip():
            raise EdgarFetchError(
                f"Sanitized document empty for {doc.filing.accession_number}."
            )
        fetched.append(
            FetchedDocument(
                doc_type=doc.doc_type,
                filename=doc.filename,
                filing=doc.filing,
                text=text,
                char_count=len(text),
            )
        )

    write_quarter_package(plan, fetched)
    sync_filings_gitignore(filings_root, [ticker_key])
    return FetchResult(plan=plan, documents=fetched)


def fetch_quarter_range(
    *,
    ticker: str,
    from_quarter: str,
    to_quarter: str,
    filings_root: Path,
    overwrite: bool = False,
    dry_run: bool = False,
    client: EdgarClient | None = None,
    config: EdgarConfig | None = None,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
) -> list[FetchResult]:
    results: list[FetchResult] = []
    for quarter in _quarter_range(from_quarter, to_quarter):
        results.append(
            fetch_quarter_package(
                ticker=ticker,
                quarter=quarter,
                filings_root=filings_root,
                overwrite=overwrite,
                dry_run=dry_run,
                client=client,
                config=config,
                calendars_path=calendars_path,
            )
        )
    return results


def ensure_filing_packages(
    *,
    filings_root: Path,
    companies: str,
    quarter: str,
    overwrite: bool = False,
    dry_run: bool = False,
    client: EdgarClient | None = None,
    config: EdgarConfig | None = None,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
) -> EnsureFetchSummary:
    cfg = config or load_edgar_config()
    edgar_client = client or EdgarClient(cfg)
    fetcher = make_json_fetcher(edgar_client)
    company_entries = resolve_companies_list(companies, fetcher=fetcher)
    summary = EnsureFetchSummary()
    quarters = parse_quarters_list(quarter)

    for normalized_quarter in quarters:
        fetch_quarters = expand_fetch_quarters(normalized_quarter)
        for ticker_key, _, _ in company_entries:
            try:
                _fetch_ticker_quarters(
                    ticker_key=ticker_key,
                    quarters=fetch_quarters,
                    filings_root=filings_root,
                    summary=summary,
                    edgar_client=edgar_client,
                    cfg=cfg,
                    calendars_path=calendars_path,
                    overwrite=overwrite,
                    dry_run=dry_run,
                )
            except EdgarFetchError as exc:
                summary.failed.append((ticker_key, normalized_quarter, str(exc)))

    if summary.failed:
        details = "; ".join(
            f"{ticker} {q}: {message}" for ticker, q, message in summary.failed
        )
        raise EdgarFetchError(
            f"EDGAR fetch failed for {len(summary.failed)} package(s): {details}"
        )
    if not dry_run:
        sync_filings_gitignore(
            filings_root,
            [ticker_key for ticker_key, _, _ in company_entries],
        )
    return summary


def ensure_filing_packages_for_quarter_end(
    *,
    filings_root: Path,
    companies: str,
    quarter_end_run: QuarterEndRun,
    overwrite: bool = False,
    dry_run: bool = False,
    client: EdgarClient | None = None,
    config: EdgarConfig | None = None,
    calendars_path: Path = DEFAULT_FISCAL_CALENDARS_PATH,
) -> EnsureFetchSummary:
    cfg = config or load_edgar_config()
    edgar_client = client or EdgarClient(cfg)
    summary = EnsureFetchSummary()

    for ticker_key, normalized_quarter in sorted(
        quarter_end_run.company_quarters.items()
    ):
        fetch_quarters = expand_fetch_quarters(normalized_quarter)
        try:
            for quarter in fetch_quarters:
                override = _anchor_override_for_quarter(
                    ticker_key,
                    quarter,
                    quarter_end_run.anchor_date,
                    calendars_path=calendars_path,
                ) if quarter == normalized_quarter else None
                _fetch_ticker_quarters(
                    ticker_key=ticker_key,
                    quarters=[quarter],
                    filings_root=filings_root,
                    summary=summary,
                    edgar_client=edgar_client,
                    cfg=cfg,
                    calendars_path=calendars_path,
                    overwrite=overwrite,
                    dry_run=dry_run,
                    period_end_override=override,
                    period_end_override_quarter=quarter if override else None,
                )
        except EdgarFetchError as exc:
            summary.failed.append((ticker_key, normalized_quarter, str(exc)))

    if summary.failed:
        details = "; ".join(
            f"{ticker} {q}: {message}" for ticker, q, message in summary.failed
        )
        raise EdgarFetchError(
            f"EDGAR fetch failed for {len(summary.failed)} package(s): {details}"
        )
    if not dry_run:
        sync_filings_gitignore(
            filings_root,
            list(quarter_end_run.company_quarters.keys()),
        )
    return summary
