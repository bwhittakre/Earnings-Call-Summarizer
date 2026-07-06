from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.ingest.edgar.cik_lookup import accession_to_path, format_cik
from src.ingest.edgar.config import EdgarConfig, load_edgar_config
from src.ingest.edgar.models import EdgarFetchError

DEFAULT_CACHE_ROOT = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "output_confidence"
    / "edgar_cache"
)


class EdgarClient:
    def __init__(
        self,
        config: EdgarConfig | None = None,
        *,
        cache_root: Path = DEFAULT_CACHE_ROOT,
    ):
        self.config = config or load_edgar_config()
        if not self.config.user_agent:
            raise EdgarFetchError(
                "EDGAR user_agent is required in config/edgar.yaml for SEC fair access."
            )
        self.cache_root = cache_root
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self._min_interval = 1.0 / max(self.config.rate_limit_rps, 0.1)
        self._last_request_at = 0.0

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request_at = time.monotonic()

    def fetch_bytes(self, url: str, *, cache_name: str | None = None) -> bytes:
        cache_path = self.cache_root / cache_name if cache_name else None
        if cache_path and cache_path.is_file():
            return cache_path.read_bytes()

        self._throttle()
        request = Request(url, headers={"User-Agent": self.config.user_agent})
        try:
            with urlopen(request, timeout=60) as response:
                payload = response.read()
        except HTTPError as exc:
            raise EdgarFetchError(f"SEC HTTP error for {url}: {exc}") from exc
        except URLError as exc:
            raise EdgarFetchError(f"SEC network error for {url}: {exc}") from exc

        if cache_path:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(payload)
        return payload

    def fetch_json(self, url: str, *, cache_name: str | None = None) -> dict:
        raw = self.fetch_bytes(url, cache_name=cache_name)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise EdgarFetchError(f"Invalid JSON from {url}") from exc
        if not isinstance(payload, dict):
            raise EdgarFetchError(f"Expected JSON object from {url}")
        return payload

    def fetch_text(self, url: str, *, cache_name: str | None = None) -> str:
        raw = self.fetch_bytes(url, cache_name=cache_name)
        for encoding in ("utf-8", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def fetch_submissions(self, cik: int) -> dict:
        cik_text = format_cik(cik)
        url = f"https://data.sec.gov/submissions/CIK{cik_text}.json"
        return self.fetch_json(url, cache_name=f"submissions/CIK{cik_text}.json")

    def fetch_submissions_file(self, filename: str) -> dict:
        url = f"https://data.sec.gov/submissions/{filename}"
        return self.fetch_json(url, cache_name=f"submissions/{filename}")

    def filing_document_url(self, cik: int, accession_number: str, primary_document: str) -> str:
        cik_int = int(cik)
        accession_path = accession_to_path(accession_number)
        return (
            f"https://www.sec.gov/Archives/edgar/data/{cik_int}/"
            f"{accession_path}/{primary_document}"
        )

    def fetch_filing_document(
        self,
        cik: int,
        accession_number: str,
        primary_document: str,
    ) -> str:
        url = self.filing_document_url(cik, accession_number, primary_document)
        cache_name = (
            f"documents/{cik}/{accession_to_path(accession_number)}/{primary_document}"
        )
        return self.fetch_text(url, cache_name=cache_name)


def make_json_fetcher(client: EdgarClient) -> Callable[[str], dict]:
    def fetcher(url: str) -> dict:
        return client.fetch_json(url)

    return fetcher
