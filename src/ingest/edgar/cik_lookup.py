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
_TICKER_PATTERN = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z])?$")


def _normalize_ticker(value: str) -> str:
    return value.strip().upper()


def _normalize_company_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


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


def _load_company_tickers(fetcher, cache_path: Path = DEFAULT_CACHE_PATH) -> dict:
    payload = _load_cached_tickers(cache_path)
    if payload is None:
        payload = fetcher(COMPANY_TICKERS_URL)
        if not isinstance(payload, dict):
            raise EdgarFetchError("SEC company_tickers.json returned unexpected payload.")
        _save_cached_tickers(cache_path, payload)
    return payload


def lookup_cik(
    ticker: str,
    *,
    fetcher,
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> tuple[int, str]:
    normalized = _normalize_ticker(ticker)
    payload = _load_company_tickers(fetcher, cache_path=cache_path)

    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        entry_ticker = _normalize_ticker(str(entry.get("ticker", "")))
        if entry_ticker == normalized:
            cik = int(entry["cik_str"])
            title = str(entry.get("title", normalized))
            return cik, title

    raise EdgarFetchError(f"Ticker {normalized!r} not found in SEC company_tickers.json.")


def _looks_like_ticker(value: str) -> bool:
    return bool(_TICKER_PATTERN.match(value.strip().upper()))


def resolve_company_identifier(
    value: str,
    *,
    fetcher,
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> tuple[str, int, str]:
    stripped = value.strip()
    if not stripped:
        raise EdgarFetchError("Company identifier cannot be empty.")

    if _looks_like_ticker(stripped):
        cik, title = lookup_cik(stripped, fetcher=fetcher, cache_path=cache_path)
        return _normalize_ticker(stripped), cik, title

    needle = _normalize_company_name(stripped)
    if not needle:
        raise EdgarFetchError(f"Invalid company identifier: {value!r}.")

    payload = _load_company_tickers(fetcher, cache_path=cache_path)
    scored_matches: list[tuple[int, str, int, str]] = []
    for entry in payload.values():
        if not isinstance(entry, dict):
            continue
        ticker = _normalize_ticker(str(entry.get("ticker", "")))
        title = str(entry.get("title", ticker))
        normalized_title = _normalize_company_name(title)
        if not ticker:
            continue
        cik = int(entry["cik_str"])
        if normalized_title == needle:
            scored_matches.append((0, ticker, cik, title))
            continue
        if normalized_title.startswith(needle):
            scored_matches.append((1, ticker, cik, title))
            continue
        if f" {needle} " in f" {normalized_title} ":
            scored_matches.append((2, ticker, cik, title))

    if not scored_matches:
        raise EdgarFetchError(f"Company {value!r} not found in SEC company_tickers.json.")

    scored_matches.sort(key=lambda item: (item[0], len(item[3]), item[1]))
    best_rank = scored_matches[0][0]
    best = [item for item in scored_matches if item[0] == best_rank]
    if len(best) > 1:
        options = ", ".join(f"{title} ({ticker})" for _, ticker, _, title in best[:5])
        raise EdgarFetchError(
            f"Ambiguous company name {value!r}. Candidates: {options}."
        )
    _, ticker, cik, title = best[0]
    return ticker, cik, title


def resolve_companies_list(
    companies: str,
    *,
    fetcher,
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> list[tuple[str, int, str]]:
    resolved: list[tuple[str, int, str]] = []
    for part in companies.split(","):
        part = part.strip()
        if not part:
            continue
        resolved.append(
            resolve_company_identifier(part, fetcher=fetcher, cache_path=cache_path)
        )
    if not resolved:
        raise EdgarFetchError("--companies must list at least one company or ticker.")
    return resolved


def normalize_companies_to_tickers(
    companies: str,
    *,
    fetcher,
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> str:
    return ",".join(
        ticker
        for ticker, _, _ in resolve_companies_list(
            companies,
            fetcher=fetcher,
            cache_path=cache_path,
        )
    )


def format_cik(cik: int) -> str:
    return f"{cik:010d}"


def accession_to_path(accession_number: str) -> str:
    return re.sub(r"[^0-9]", "", accession_number)
