from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from src.ingest.edgar.submissions import iter_submission_filings
from src.ingest.filings.fiscal import normalize_quarter_label
from src.market.fiscal_resolver import (
    _calendar_fiscal_quarter_end,
    _offset_fiscal_quarter_end,
)
from src.market.quarter_labels import format_quarter_label

DEFAULT_PROFILE_CACHE_DIR = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "output_confidence"
    / "edgar_cache"
    / "fiscal_profiles"
)


@dataclass(frozen=True)
class FiscalProfile:
    ticker: str
    company_name: str
    fiscal_year_end: str
    calendar_type: str
    fye_month: int
    fye_day: int
    quarter_ends: dict[str, str]

    def to_dict(self) -> dict:
        return {
            "ticker": self.ticker,
            "company_name": self.company_name,
            "fiscal_year_end": self.fiscal_year_end,
            "calendar_type": self.calendar_type,
            "fye_month": self.fye_month,
            "fye_day": self.fye_day,
            "quarter_ends": dict(sorted(self.quarter_ends.items())),
        }

    @classmethod
    def from_dict(cls, payload: dict) -> FiscalProfile:
        fye = str(payload.get("fiscal_year_end", "1231"))
        return cls(
            ticker=str(payload["ticker"]).upper(),
            company_name=str(payload.get("company_name", payload["ticker"])),
            fiscal_year_end=fye,
            calendar_type=str(payload.get("calendar_type", "offset_fiscal")),
            fye_month=int(payload.get("fye_month", int(fye[:2]))),
            fye_day=int(payload.get("fye_day", int(fye[2:4]))),
            quarter_ends={
                normalize_quarter_label(key): str(value)
                for key, value in (payload.get("quarter_ends") or {}).items()
            },
        )


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _parse_fiscal_year_end(value: str | None) -> tuple[str, int, int]:
    raw = (value or "1231").strip()
    if len(raw) != 4 or not raw.isdigit():
        return "1231", 12, 31
    month = int(raw[:2])
    day = int(raw[2:4])
    return raw, month, day


def _infer_calendar_type(fiscal_year_end: str) -> str:
    if fiscal_year_end == "1231":
        return "calendar_fiscal"
    return "offset_fiscal"


def _dates_close(left: date, right: date, *, tolerance_days: int = 5) -> bool:
    return abs((left - right).days) <= tolerance_days


def _infer_quarter_label(
    report_date: date,
    *,
    calendar_type: str,
    fye_month: int,
    fye_day: int,
) -> str | None:
    best_label: str | None = None
    best_delta = tolerance_days = 5
    for fiscal_year in range(report_date.year - 1, report_date.year + 3):
        for quarter_num in range(1, 5):
            if calendar_type == "calendar_fiscal":
                expected = _calendar_fiscal_quarter_end(fiscal_year, quarter_num)
            elif calendar_type == "offset_fiscal":
                expected = _offset_fiscal_quarter_end(
                    fiscal_year,
                    quarter_num,
                    fye_month=fye_month,
                    fye_day=fye_day,
                )
            else:
                continue
            delta = abs((expected - report_date).days)
            if delta <= tolerance_days and (best_label is None or delta < best_delta):
                best_label = format_quarter_label(True, fiscal_year, quarter_num)
                best_delta = delta
    return best_label


def bootstrap_fiscal_profile(
    ticker: str,
    company_name: str,
    submissions: dict,
) -> FiscalProfile:
    ticker_key = ticker.strip().upper()
    fiscal_year_end, fye_month, fye_day = _parse_fiscal_year_end(
        submissions.get("fiscalYearEnd")
    )
    calendar_type = _infer_calendar_type(fiscal_year_end)

    quarter_ends: dict[str, str] = {}
    for row in iter_submission_filings(submissions):
        form = str(row.get("form", "")).upper()
        if not (form.startswith("10-Q") or form.startswith("10-K")):
            continue
        report_date = _parse_iso_date(row.get("reportDate"))
        if report_date is None:
            continue
        label = _infer_quarter_label(
            report_date,
            calendar_type=calendar_type,
            fye_month=fye_month,
            fye_day=fye_day,
        )
        if label:
            quarter_ends[normalize_quarter_label(label)] = report_date.isoformat()

    return FiscalProfile(
        ticker=ticker_key,
        company_name=company_name,
        fiscal_year_end=fiscal_year_end,
        calendar_type=calendar_type,
        fye_month=fye_month,
        fye_day=fye_day,
        quarter_ends=quarter_ends,
    )


def profile_cache_path(
    ticker: str,
    cache_dir: Path = DEFAULT_PROFILE_CACHE_DIR,
) -> Path:
    return cache_dir / f"{ticker.strip().upper()}.json"


def load_cached_fiscal_profile(
    ticker: str,
    *,
    cache_dir: Path = DEFAULT_PROFILE_CACHE_DIR,
) -> FiscalProfile | None:
    path = profile_cache_path(ticker, cache_dir=cache_dir)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return FiscalProfile.from_dict(payload)
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None
    return None


def save_fiscal_profile(
    profile: FiscalProfile,
    *,
    cache_dir: Path = DEFAULT_PROFILE_CACHE_DIR,
) -> Path:
    path = profile_cache_path(profile.ticker, cache_dir=cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def load_or_bootstrap_fiscal_profile(
    ticker: str,
    company_name: str,
    submissions: dict,
    *,
    cache_dir: Path = DEFAULT_PROFILE_CACHE_DIR,
    refresh: bool = False,
) -> FiscalProfile:
    ticker_key = ticker.strip().upper()
    if not refresh:
        cached = load_cached_fiscal_profile(ticker_key, cache_dir=cache_dir)
        if cached is not None:
            return cached
    profile = bootstrap_fiscal_profile(ticker_key, company_name, submissions)
    save_fiscal_profile(profile, cache_dir=cache_dir)
    return profile


def get_fiscal_profile_for_ticker(
    ticker: str,
    *,
    calendars_path,
    submissions: dict | None = None,
    company_name: str | None = None,
) -> FiscalProfile | None:
    from src.market.fiscal_calendar import load_fiscal_calendars

    ticker_key = ticker.strip().upper()
    try:
        config = load_fiscal_calendars(calendars_path)
    except Exception:
        config = {}
    if ticker_key in config:
        return None
    if submissions is None:
        return load_cached_fiscal_profile(ticker_key)
    return load_or_bootstrap_fiscal_profile(
        ticker_key,
        company_name or ticker_key,
        submissions,
    )
