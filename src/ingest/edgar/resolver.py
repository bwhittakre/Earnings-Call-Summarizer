from __future__ import annotations

from pathlib import Path

from src.ingest.edgar.cik_lookup import lookup_cik
from src.ingest.edgar.client import EdgarClient, make_json_fetcher
from src.ingest.edgar.config import EdgarConfig, load_edgar_config
from src.ingest.edgar.models import EdgarFetchError, FetchResult, FetchedDocument
from src.ingest.edgar.selector import build_quarter_fetch_plan
from src.ingest.edgar.writer import should_skip_fetch, write_quarter_package
from src.ingest.filings.fiscal import parse_quarters_list, quarter_sort_key
from src.ingest.filings.sec_sanitize import sanitize_filing_text
from src.market.quarter_labels import format_quarter_label, parse_quarter_label


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


def plan_quarter_fetch(
    *,
    ticker: str,
    quarter: str,
    filings_root: Path,
    client: EdgarClient | None = None,
    config: EdgarConfig | None = None,
):
    cfg = config or load_edgar_config()
    edgar_client = client or EdgarClient(cfg)
    cik, _ = lookup_cik(ticker, fetcher=make_json_fetcher(edgar_client))
    submissions = edgar_client.fetch_submissions(cik)
    return build_quarter_fetch_plan(
        ticker=ticker,
        quarter=quarter,
        filings_root=filings_root,
        config=cfg,
        client=edgar_client,
        submissions=submissions,
        cik=cik,
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
) -> FetchResult:
    cfg = config or load_edgar_config()
    edgar_client = client or EdgarClient(cfg)
    cik, _ = lookup_cik(ticker, fetcher=make_json_fetcher(edgar_client))
    submissions = edgar_client.fetch_submissions(cik)
    plan = build_quarter_fetch_plan(
        ticker=ticker,
        quarter=quarter,
        filings_root=filings_root,
        config=cfg,
        client=edgar_client,
        submissions=submissions,
        cik=cik,
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
            )
        )
    return results
