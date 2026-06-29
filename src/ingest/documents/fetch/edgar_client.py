from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

SEC_BASE = "https://www.sec.gov"
SEC_DATA_BASE = "https://data.sec.gov"
DEFAULT_USER_AGENT = "EarningsCallSummarizer research@example.com"


@dataclass
class EdgarClient:
    user_agent: str
    min_interval_seconds: float = 0.2
    _last_request_at: float = 0.0
    _get: Callable[..., httpx.Response] | None = None
    _request_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_env(cls) -> EdgarClient:
        user_agent = os.getenv("SEC_EDGAR_USER_AGENT", DEFAULT_USER_AGENT)
        return cls(user_agent=user_agent)

    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            time.sleep(self.min_interval_seconds - elapsed)

    def get(self, url: str, *, timeout: float = 60.0) -> httpx.Response:
        with self._request_lock:
            self._throttle()
            headers = {
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
            if self._get is not None:
                response = self._get(url, headers=headers, timeout=timeout)
            else:
                response = httpx.get(url, headers=headers, timeout=timeout, follow_redirects=True)
            self._last_request_at = time.monotonic()
        response.raise_for_status()
        return response

    def get_text(self, url: str) -> str:
        return self.get(url).text

    def get_json(self, url: str) -> dict:
        return self.get(url).json()


def normalize_cik(cik: str) -> str:
    digits = re.sub(r"\D", "", cik)
    return digits.zfill(10)


def cik_int(cik: str) -> int:
    return int(normalize_cik(cik).lstrip("0") or "0")


def accession_no_dashes(accession: str) -> str:
    return accession.replace("-", "")


def filing_archive_base(cik: str, accession: str) -> str:
    return f"{SEC_BASE}/Archives/edgar/data/{cik_int(cik)}/{accession_no_dashes(accession)}"


def fetch_company_tickers(client: EdgarClient) -> dict:
    return client.get_json(f"{SEC_BASE}/files/company_tickers.json")


def resolve_cik_from_tickers(ticker: str, tickers: dict) -> str | None:
    target = ticker.strip().upper()
    for entry in tickers.values():
        if str(entry.get("ticker", "")).upper() == target:
            return normalize_cik(str(entry.get("cik_str", entry.get("cik", ""))))
    return None


def fetch_submissions(client: EdgarClient, cik: str) -> dict:
    normalized = normalize_cik(cik)
    return client.get_json(f"{SEC_DATA_BASE}/submissions/CIK{normalized}.json")
