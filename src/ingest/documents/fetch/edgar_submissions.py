from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass
class FilingRecord:
    form: str
    accession_number: str
    filing_date: date
    report_date: date | None
    primary_document: str
    items: str | None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def filings_from_submissions_payload(payload: dict) -> list[FilingRecord]:
    recent = payload.get("filings", payload).get("recent", payload)
    if not isinstance(recent, dict) or "form" not in recent:
        return []
    forms = recent.get("form", [])
    records: list[FilingRecord] = []
    report_dates = recent.get("reportDate", [None] * len(forms))
    items_list = recent.get("items") or [None] * len(forms)
    for index, form in enumerate(forms):
        filing_date = _parse_date(recent["filingDate"][index])
        if filing_date is None:
            continue
        records.append(
            FilingRecord(
                form=form,
                accession_number=recent["accessionNumber"][index],
                filing_date=filing_date,
                report_date=_parse_date(
                    report_dates[index] if index < len(report_dates) else None
                ),
                primary_document=recent["primaryDocument"][index],
                items=items_list[index] if index < len(items_list) else None,
            )
        )
    return records


def iter_recent_filings(submissions: dict) -> list[FilingRecord]:
    return filings_from_submissions_payload(submissions)


def load_all_filings(submissions: dict, client, cik: str) -> list[FilingRecord]:
    from src.ingest.documents.fetch.edgar_client import SEC_DATA_BASE

    records = filings_from_submissions_payload(submissions)
    seen = {record.accession_number for record in records}
    files_meta = submissions.get("filings", {}).get("files", [])
    for entry in files_meta:
        name = entry.get("name")
        if not name:
            continue
        url = f"{SEC_DATA_BASE}/submissions/{name}"
        try:
            payload = client.get_json(url)
        except Exception:
            continue
        for record in filings_from_submissions_payload(payload):
            if record.accession_number in seen:
                continue
            seen.add(record.accession_number)
            records.append(record)
    return records


def find_filings(
    filings: list[FilingRecord],
    *,
    form: str,
    start: date | None = None,
    end: date | None = None,
    report_date: date | None = None,
    item_contains: str | None = None,
    filed_on_or_before: date | None = None,
) -> list[FilingRecord]:
    matches: list[FilingRecord] = []
    for record in filings:
        if record.form != form:
            continue
        if filed_on_or_before and record.filing_date > filed_on_or_before:
            continue
        if start and record.filing_date < start:
            continue
        if end and record.filing_date > end:
            continue
        if report_date and record.report_date != report_date:
            continue
        if item_contains and item_contains not in (record.items or ""):
            continue
        matches.append(record)
    return matches
