from __future__ import annotations

from typing import Iterable

from src.ingest.edgar.client import EdgarClient


def _columnar_filings(payload: dict) -> list[dict[str, str]]:
    keys = (
        "accessionNumber",
        "form",
        "filingDate",
        "reportDate",
        "primaryDocument",
    )
    columns = {key: payload.get(key, []) for key in keys}
    count = max((len(values) for values in columns.values()), default=0)
    rows: list[dict[str, str]] = []
    for index in range(count):
        row = {
            key: columns[key][index]
            for key in keys
            if index < len(columns[key])
        }
        if row.get("accessionNumber"):
            rows.append(row)
    return rows


def iter_submission_filings(
    submissions: dict,
    client: EdgarClient | None = None,
) -> Iterable[dict[str, str]]:
    filings = submissions.get("filings", {})
    recent = filings.get("recent")
    if isinstance(recent, dict):
        yield from _columnar_filings(recent)

    if client is None:
        return

    for file_info in filings.get("files", []) or []:
        if not isinstance(file_info, dict):
            continue
        name = file_info.get("name")
        if not name:
            continue
        payload = client.fetch_submissions_file(str(name))
        yield from _columnar_filings(payload)


def iter_all_filings(client: EdgarClient, submissions: dict) -> Iterable[dict[str, str]]:
    yield from iter_submission_filings(submissions, client)
