from __future__ import annotations

import json
import threading
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from src.ingest.documents.fetch.edgar_client import EdgarClient, fetch_submissions
from src.ingest.documents.fetch.edgar_submissions import FilingRecord, load_all_filings

FILINGS_CACHE_FILENAME = ".sec_filings_index.json"
DEFAULT_CACHE_MAX_AGE_HOURS = 24.0
_cache_lock = threading.Lock()


def _cache_path(ticker_folder: Path) -> Path:
    return ticker_folder / FILINGS_CACHE_FILENAME


def _serialize_filing(record: FilingRecord) -> dict:
    payload = asdict(record)
    payload["filing_date"] = record.filing_date.isoformat()
    payload["report_date"] = (
        record.report_date.isoformat() if record.report_date else None
    )
    return payload


def _deserialize_filing(payload: dict) -> FilingRecord:
    return FilingRecord(
        form=payload["form"],
        accession_number=payload["accession_number"],
        filing_date=date.fromisoformat(payload["filing_date"]),
        report_date=(
            date.fromisoformat(payload["report_date"])
            if payload.get("report_date")
            else None
        ),
        primary_document=payload["primary_document"],
        items=payload.get("items"),
    )


def load_filings_cache(
    ticker_folder: Path,
    *,
    max_age_hours: float = DEFAULT_CACHE_MAX_AGE_HOURS,
) -> list[FilingRecord] | None:
    path = _cache_path(ticker_folder)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(payload["fetched_at"])
        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
        if age_hours > max_age_hours:
            return None
        return [_deserialize_filing(item) for item in payload["filings"]]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_filings_cache(ticker_folder: Path, filings: list[FilingRecord]) -> None:
    ticker_folder.mkdir(parents=True, exist_ok=True)
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "filings": [_serialize_filing(record) for record in filings],
    }
    _cache_path(ticker_folder).write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )


def get_ticker_filings(
    client: EdgarClient,
    cik: str,
    ticker_folder: Path,
    *,
    force_refresh: bool = False,
    max_age_hours: float = DEFAULT_CACHE_MAX_AGE_HOURS,
) -> list[FilingRecord]:
    if not force_refresh:
        cached = load_filings_cache(ticker_folder, max_age_hours=max_age_hours)
        if cached is not None:
            return cached
    with _cache_lock:
        if not force_refresh:
            cached = load_filings_cache(ticker_folder, max_age_hours=max_age_hours)
            if cached is not None:
                return cached
        submissions = fetch_submissions(client, cik)
        filings = load_all_filings(submissions, client, cik)
        save_filings_cache(ticker_folder, filings)
        return filings
