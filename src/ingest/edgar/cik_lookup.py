from __future__ import annotations

import json
import re
from pathlib import Path

from src.ingest.edgar.models import EdgarFetchError

COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
DEFAULT_CACHE_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "output_confidence"
    / "edgar_cache"
    / "company_tickers.json"
)


def _normalize_ticker(value: str) -> str:
    return value.strip().upper()


def _load_cached_tickers(cache_path: Path) -> dict | None:
    if not cache_path.is_file():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_cached_tickers(cache_path: Path, payload: dict) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def lookup_cik(
    ticker: str,
    *,
    fetcher,
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> tuple[int, str]:
    normalized = _normalize_ticker(ticker)
    payload = _load_cached_tickers(cache_path)
    if payload is None:
        payload = fetcher(COMPANY_TICKERS_URL)
        if not isinstance(payload, dict):
            raise EdgarFetchError("SEC company_tickers.json returned unexpected payload.")
        _save_cached_tickers(cache_path, payload)

    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        entry_ticker = _normalize_ticker(str(entry.get("ticker", "")))
        if entry_ticker == normalized:
            cik = int(entry["cik_str"])
            title = str(entry.get("title", normalized))
            return cik, title

    raise EdgarFetchError(f"Ticker {normalized!r} not found in SEC company_tickers.json.")


def format_cik(cik: int) -> str:
    return f"{cik:010d}"


def accession_to_path(accession_number: str) -> str:
    return re.sub(r"[^0-9]", "", accession_number)
