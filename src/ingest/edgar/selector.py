from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING, Iterable

from src.ingest.edgar.client import EdgarClient
from src.ingest.edgar.config import EdgarConfig
from src.ingest.edgar.models import EdgarFetchError, FilingRef, PlannedDocument, QuarterFetchPlan
from src.ingest.edgar.submissions import iter_all_filings
from src.market.fiscal_resolver import (
    expected_period_end_date,
    fiscal_year_end_date,
    manifest_as_of_date_text,
)
from src.ingest.filings.fiscal import fiscal_year_prefix, is_q4_quarter, normalize_quarter_label

if TYPE_CHECKING:
    from src.ingest.edgar.fiscal_profile import FiscalProfile


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _build_filing_ref(cik: int, row: dict[str, str], client: EdgarClient) -> FilingRef:
    accession = row["accessionNumber"]
    primary = row.get("primaryDocument") or ""
    if not primary:
        raise EdgarFetchError(f"Missing primaryDocument for accession {accession}.")
    return FilingRef(
        form=str(row.get("form", "")).upper(),
        accession_number=accession,
        filing_date=_parse_iso_date(row.get("filingDate")) or date.min,
        report_date=_parse_iso_date(row.get("reportDate")),
        primary_document=primary,
        source_url=client.filing_document_url(cik, accession, primary),
    )


def _dates_close(left: date | None, right: date, *, tolerance_days: int = 3) -> bool:
    if left is None:
        return False
    return abs((left - right).days) <= tolerance_days


def _select_period_form(
    filings: Iterable[dict[str, str]],
    *,
    cik: int,
    client: EdgarClient,
    form_prefix: str,
    target_date: date,
) -> FilingRef:
    matches: list[tuple[date, FilingRef]] = []
    for row in filings:
        form = str(row.get("form", "")).upper()
        if not form.startswith(form_prefix):
            continue
        report_date = _parse_iso_date(row.get("reportDate"))
        if not _dates_close(report_date, target_date):
            continue
        filing = _build_filing_ref(cik, row, client)
        matches.append((report_date or target_date, filing))

    if not matches:
        raise EdgarFetchError(
            f"No {form_prefix} found with report date near {target_date.isoformat()}."
        )
    matches.sort(key=lambda item: item[0], reverse=True)
    return matches[0][1]


def _looks_like_earnings_8k(text: str) -> bool:
    sample = text[:12000].lower()
    return "item 2.02" in sample or "results of operations" in sample


def _select_earnings_8k(
    filings: Iterable[dict[str, str]],
    *,
    cik: int,
    client: EdgarClient,
    period_end: date,
    window_days: int,
) -> FilingRef:
    window_end = period_end + timedelta(days=window_days)
    candidates: list[tuple[date, dict[str, str]]] = []
    for row in filings:
        form = str(row.get("form", "")).upper()
        if form != "8-K":
            continue
        filing_date = _parse_iso_date(row.get("filingDate"))
        if filing_date is None:
            continue
        if filing_date < period_end or filing_date > window_end:
            continue
        candidates.append((filing_date, row))

    candidates.sort(key=lambda item: item[0])
    for _, row in candidates[:8]:
        filing = _build_filing_ref(cik, row, client)
        try:
            raw = client.fetch_filing_document(
                cik,
                filing.accession_number,
                filing.primary_document,
            )
        except EdgarFetchError:
            continue
        if _looks_like_earnings_8k(raw):
            return filing

    if candidates:
        filing = _build_filing_ref(cik, candidates[0][1], client)
        return filing

    raise EdgarFetchError(
        f"No earnings 8-K found within {window_days} days after {period_end.isoformat()}."
    )


def build_quarter_fetch_plan(
    *,
    ticker: str,
    quarter: str,
    filings_root,
    config: EdgarConfig,
    client: EdgarClient,
    submissions: dict,
    cik: int,
    fiscal_profile: FiscalProfile | None = None,
    period_end_override: date | None = None,
) -> QuarterFetchPlan:
    normalized = normalize_quarter_label(quarter)
    ticker_key = ticker.strip().upper()
    period_end = period_end_override or expected_period_end_date(
        ticker_key,
        normalized,
        fiscal_profile=fiscal_profile,
    )
    if period_end_override is not None:
        as_of_date_text = (
            f"({period_end.month:02d},{period_end.day:02d},{period_end.year})"
        )
    else:
        as_of_date_text = manifest_as_of_date_text(
            ticker_key,
            normalized,
            fiscal_profile=fiscal_profile,
        )
    fiscal_year = fiscal_year_prefix(normalized)
    company_folder = config.company_folders.get(ticker_key, ticker_key)
    company_name = config.company_names.get(ticker_key, ticker_key)
    folder = filings_root / ticker_key / company_folder / fiscal_year / normalized

    all_filings = list(iter_all_filings(client, submissions))
    documents: list[PlannedDocument] = []

    if is_q4_quarter(normalized):
        ten_k_target = period_end_override or fiscal_year_end_date(
            ticker_key,
            normalized,
            fiscal_profile=fiscal_profile,
        )
        ten_k = _select_period_form(
            all_filings,
            cik=cik,
            client=client,
            form_prefix="10-K",
            target_date=ten_k_target,
        )
        documents.append(
            PlannedDocument(doc_type="10-K", filename="10-K.txt", filing=ten_k)
        )
    else:
        ten_q = _select_period_form(
            all_filings,
            cik=cik,
            client=client,
            form_prefix="10-Q",
            target_date=period_end,
        )
        documents.append(
            PlannedDocument(doc_type="10-Q", filename="10-Q.txt", filing=ten_q)
        )

    eight_k = _select_earnings_8k(
        all_filings,
        cik=cik,
        client=client,
        period_end=period_end,
        window_days=config.earnings_8k_window_days,
    )
    documents.append(
        PlannedDocument(doc_type="8-K", filename="8-K.txt", filing=eight_k)
    )

    return QuarterFetchPlan(
        ticker=ticker_key,
        quarter=normalized,
        fiscal_year=fiscal_year,
        period_end=period_end,
        as_of_date_text=as_of_date_text,
        company_name=company_name,
        folder=folder,
        documents=tuple(documents),
        is_q4=is_q4_quarter(normalized),
    )
