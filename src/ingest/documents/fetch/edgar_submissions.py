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


def iter_recent_filings(submissions: dict) -> list[FilingRecord]:
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    records: list[FilingRecord] = []
    for index, form in enumerate(forms):
        records.append(
            FilingRecord(
                form=form,
                accession_number=recent["accessionNumber"][index],
                filing_date=_parse_date(recent["filingDate"][index]),
                report_date=_parse_date(recent.get("reportDate", [None] * len(forms))[index]),
                primary_document=recent["primaryDocument"][index],
                items=(recent.get("items") or [None] * len(forms))[index],
            )
        )
    return records


def find_filings(
    submissions: dict,
    *,
    form: str,
    start: date | None = None,
    end: date | None = None,
    report_date: date | None = None,
    item_contains: str | None = None,
) -> list[FilingRecord]:
    matches: list[FilingRecord] = []
    for record in iter_recent_filings(submissions):
        if record.form != form:
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
