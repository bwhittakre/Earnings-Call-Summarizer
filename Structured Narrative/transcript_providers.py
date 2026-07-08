#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Swappable earnings-call transcript sourcing layer.
==================================================

The whole point of this module is that *nothing downstream depends on the
vendor*. Every provider returns the same normalized ``Transcript`` object, so
the dimension scorer, evidence validation and the join to the quant spine never
know or care where the text came from. Swapping FMP for LSEG, a manual paste, or
any other API later is a one-class change here.

Providers implemented:
  * ``FmpApiProvider``   -> Financial Modeling Prep earnings-call transcript API
  * ``LocalFileProvider`` -> reads ``transcripts_raw/{TICKER}_{fiscal_period}.txt``
                             (zero-cost fallback / manual paste / offline re-runs)

Select at runtime with the ``TRANSCRIPT_PROVIDER`` env var (default ``fmp``) via
``get_provider()``.

Raw API payloads are cached to ``output/transcripts/`` so repeated runs cost no
API calls and the pilot stays reproducible even if the subscription lapses.
"""
from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE_DIR = HERE / "output" / "transcripts"
LOCAL_DIR = HERE / "transcripts_raw"

FMP_STABLE_URL = "https://financialmodelingprep.com/stable/earning-call-transcript"
FMP_V3_URL = "https://financialmodelingprep.com/api/v3/earning_call_transcript/{symbol}"

# Phrases that mark the boundary between prepared remarks and the Q&A section.
# Ordered/chosen so we match the ACTUAL transition, not the operator's intro
# ("...we will conduct a question-and-answer session") — hence no bare
# "question-and-answer session" here. A "Questions & Answers:" header (common in
# Motley Fool transcripts) is the most reliable marker.
_QA_MARKERS = (
    "questions & answers:",
    "questions and answers:",
    "we will now open the call",
    "we'll now open the call",
    "open the call up for questions",
    "open the call for questions",
    "open the line for questions",
    "the first question comes from",
    "first question comes from",
    "first question is from",
    "our first question",
    "[operator instructions]",
)

# Speaker labels come in two common shapes:
#   "Andy Jassy:"                                  (colon style)
#   "Andrew R. Jassy -- President and CEO"        (Motley-Fool dash style)
# plus bare "Operator" lines.
_SPEAKER_COLON_RE = re.compile(
    r"(?:^|\n)[ \t]*([A-Z][A-Za-z.\-'’]+(?:[ \t]+[A-Z][A-Za-z.\-'’]+){0,4})[ \t]*:[ \t]",
)
_SPEAKER_DASH_RE = re.compile(
    r"(?:^|\n)[ \t]*([A-Z][A-Za-z.\-'’]+(?:[ \t]+[A-Za-z0-9.\-'’&]+){0,5})[ \t]+--[ \t]+\S",
)
_OPERATOR_LINE_RE = re.compile(r"(?:^|\n)[ \t]*(Operator)[ \t]*(?:\n|$)")

_FISCAL_RE = re.compile(r"^FY?(\d{4})-Q([1-4])$", re.IGNORECASE)


# ── Normalized transcript object (the only thing downstream code sees) ─────────
@dataclass
class Transcript:
    ticker: str
    fiscal_period: str            # e.g. "FY2024-Q3"
    call_date: str | None         # ISO date/datetime the call took place (PIT as-of)
    source_name: str              # "fmp" | "local" | ...
    raw_text: str                 # full cleaned transcript
    prepared_remarks: str
    qa_text: str
    speakers: list[str] = field(default_factory=list)
    url: str | None = None
    retrieved_at: str = ""

    @property
    def n_speakers(self) -> int:
        return len(self.speakers)

    @property
    def qa_found(self) -> bool:
        return bool(self.qa_text.strip())

    def as_meta(self) -> dict:
        d = asdict(self)
        # Don't duplicate the (potentially huge) text bodies in the meta dump.
        for k in ("raw_text", "prepared_remarks", "qa_text"):
            d.pop(k, None)
        d["n_chars"] = len(self.raw_text)
        d["n_speakers"] = self.n_speakers
        d["prepared_chars"] = len(self.prepared_remarks)
        d["qa_chars"] = len(self.qa_text)
        d["qa_found"] = self.qa_found
        return d


# ── Shared text normalization / structuring helpers ───────────────────────────
def parse_fiscal_period(fiscal_period: str) -> tuple[int, int]:
    """"FY2024-Q3" -> (2024, 3). Kept local so this module has no cross-package
    dependency (part of staying vendor/pipeline decoupled)."""
    m = _FISCAL_RE.match(fiscal_period.strip())
    if not m:
        raise ValueError(
            f"Bad fiscal_period {fiscal_period!r}; expected e.g. 'FY2024-Q3'"
        )
    return int(m.group(1)), int(m.group(2))


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    # Collapse 3+ blank lines to a paragraph break; trim trailing spaces.
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_speakers(text: str) -> list[str]:
    seen: list[str] = []
    for rx in (_SPEAKER_DASH_RE, _SPEAKER_COLON_RE, _OPERATOR_LINE_RE):
        for m in rx.finditer(text):
            name = m.group(1).strip()
            if not name or len(name) > 45:
                continue
            if name not in seen:
                seen.append(name)
    return seen


def split_prepared_qa(text: str) -> tuple[str, str]:
    lower = text.lower()
    idx = -1
    for marker in _QA_MARKERS:
        found = lower.find(marker)
        if found != -1 and (idx == -1 or found < idx):
            idx = found
    if idx == -1:
        return text, ""
    return text[:idx].strip(), text[idx:].strip()


def build_transcript(
    *,
    ticker: str,
    fiscal_period: str,
    call_date: str | None,
    source_name: str,
    content: str,
    url: str | None = None,
) -> Transcript:
    cleaned = clean_text(content)
    prepared, qa = split_prepared_qa(cleaned)
    return Transcript(
        ticker=ticker.upper(),
        fiscal_period=fiscal_period,
        call_date=call_date,
        source_name=source_name,
        raw_text=cleaned,
        prepared_remarks=prepared,
        qa_text=qa,
        speakers=extract_speakers(cleaned),
        url=url,
        retrieved_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


# ── Provider interface ─────────────────────────────────────────────────────────
class TranscriptProvider(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, ticker: str, fiscal_period: str) -> Transcript:
        """Return a normalized Transcript for one earnings event, or raise
        TranscriptNotFound."""


class TranscriptNotFound(Exception):
    pass


# ── FMP provider ────────────────────────────────────────────────────────────────
class FmpApiProvider(TranscriptProvider):
    name = "fmp"

    def __init__(self, api_key: str | None = None, cache_dir: Path = CACHE_DIR):
        self.api_key = api_key or os.getenv("FMP_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "FMP_API_KEY is not set. Add it to 'Structured Narrative/.env' "
                "or set TRANSCRIPT_PROVIDER=local to use manual transcripts."
            )
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(self, ticker: str, fiscal_period: str) -> Path:
        return self.cache_dir / f"{ticker.upper()}_{fiscal_period}.json"

    def _load_cache(self, ticker: str, fiscal_period: str) -> dict | None:
        p = self._cache_path(ticker, fiscal_period)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return None
        return None

    def _save_cache(self, ticker: str, fiscal_period: str, payload: dict) -> None:
        self._cache_path(ticker, fiscal_period).write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )

    def _request(self, ticker: str, year: int, quarter: int) -> dict:
        import requests

        params_stable = {
            "symbol": ticker.upper(),
            "year": year,
            "quarter": quarter,
            "apikey": self.api_key,
        }
        # Try the stable endpoint first, then fall back to the legacy v3 route.
        attempts = [
            (FMP_STABLE_URL, params_stable),
            (
                FMP_V3_URL.format(symbol=ticker.upper()),
                {"year": year, "quarter": quarter, "apikey": self.api_key},
            ),
        ]
        last_err: Exception | None = None
        for url, params in attempts:
            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:  # network / HTTP / JSON
                last_err = exc
                continue
            record = self._first_record(data)
            if record and record.get("content"):
                record["_endpoint"] = url
                return record
        if last_err is not None:
            raise TranscriptNotFound(
                f"FMP request failed for {ticker} {year}Q{quarter}: {last_err}"
            )
        raise TranscriptNotFound(
            f"FMP returned no transcript content for {ticker} {year}Q{quarter}."
        )

    @staticmethod
    def _first_record(data) -> dict | None:
        if isinstance(data, list):
            return data[0] if data else None
        if isinstance(data, dict):
            # Some responses wrap the list; otherwise it's already the record.
            if "content" in data:
                return data
            for v in data.values():
                if isinstance(v, list) and v:
                    return v[0]
        return None

    def fetch(self, ticker: str, fiscal_period: str) -> Transcript:
        year, quarter = parse_fiscal_period(fiscal_period)
        record = self._load_cache(ticker, fiscal_period)
        if record is None:
            record = self._request(ticker, year, quarter)
            self._save_cache(ticker, fiscal_period, record)
        content = record.get("content") or ""
        if not content.strip():
            raise TranscriptNotFound(
                f"Empty transcript for {ticker} {fiscal_period}."
            )
        return build_transcript(
            ticker=ticker,
            fiscal_period=fiscal_period,
            call_date=record.get("date"),
            source_name=self.name,
            content=content,
            url=record.get("_endpoint"),
        )


# ── Local file provider (fallback / manual paste / offline) ─────────────────────
class LocalFileProvider(TranscriptProvider):
    name = "local"

    def __init__(self, local_dir: Path = LOCAL_DIR):
        self.local_dir = Path(local_dir)

    def _candidates(self, ticker: str, fiscal_period: str) -> list[Path]:
        """Accept a few natural layouts so it doesn't matter exactly how the
        files were dropped in."""
        t = ticker.upper()
        return [
            self.local_dir / f"{t}_{fiscal_period}.txt",   # transcripts_raw/AMZN_FY2024-Q1.txt
            HERE / t / f"{fiscal_period}.txt",              # AMZN/FY2024-Q1.txt
            HERE / t / f"{t}_{fiscal_period}.txt",          # AMZN/AMZN_FY2024-Q1.txt
            self.local_dir / t / f"{fiscal_period}.txt",    # transcripts_raw/AMZN/FY2024-Q1.txt
        ]

    def fetch(self, ticker: str, fiscal_period: str) -> Transcript:
        candidates = self._candidates(ticker, fiscal_period)
        path = next((p for p in candidates if p.exists()), None)
        if path is None:
            locations = "\n  ".join(str(p) for p in candidates)
            raise TranscriptNotFound(
                f"No local transcript for {ticker} {fiscal_period}. Looked in:\n  {locations}"
            )
        content = path.read_text(encoding="utf-8", errors="replace")
        return build_transcript(
            ticker=ticker,
            fiscal_period=fiscal_period,
            call_date=None,
            source_name=self.name,
            content=content,
            url=str(path),
        )


# ── Factory ──────────────────────────────────────────────────────────────────
def get_provider(name: str | None = None) -> TranscriptProvider:
    name = (name or os.getenv("TRANSCRIPT_PROVIDER") or "fmp").strip().lower()
    if name == "fmp":
        return FmpApiProvider()
    if name == "local":
        return LocalFileProvider()
    raise ValueError(
        f"Unknown TRANSCRIPT_PROVIDER {name!r}. Use 'fmp' or 'local'."
    )
