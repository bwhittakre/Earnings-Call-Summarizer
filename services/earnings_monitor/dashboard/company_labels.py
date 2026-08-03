"""Display labels that pair tickers with short company names."""

from __future__ import annotations

import re
import sys
from functools import lru_cache
from pathlib import Path

# Short brand names for the Roz universe. Prefer these over legal entity names.
COMPANY_BRANDS: dict[str, str] = {
    "AAPL": "Apple",
    "ACN": "Accenture",
    "ADBE": "Adobe",
    "ADI": "Analog Devices",
    "ADSK": "Autodesk",
    "AMAT": "Applied Materials",
    "AMZN": "Amazon",
    "APH": "Amphenol",
    "AVGO": "Broadcom",
    "CRM": "Salesforce",
    "CTSH": "Cognizant",
    "IBM": "IBM",
    "INTU": "Intuit",
    "LRCX": "Lam Research",
    "MSFT": "Microsoft",
    "MU": "Micron",
    "NVDA": "NVIDIA",
    "ORCL": "Oracle",
    "TEL": "TE Connectivity",
    "TXN": "Texas Instruments",
}

_LEGAL_SUFFIXES = (
    r",?\s+Incorporated$",
    r",?\s+Corporation$",
    r",?\s+Company$",
    r",?\s+Corp\.?$",
    r",?\s+Inc\.?$",
    r",?\s+Ltd\.?$",
    r",?\s+Limited$",
    r",?\s+plc$",
    r",?\s+PLC$",
    r",?\s+Co\.?$",
)


def _shorten_legal_name(company_name: str) -> str:
    name = company_name.strip()
    for pattern in _LEGAL_SUFFIXES:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE).rstrip(" ,")
    if name.lower().endswith(".com"):
        name = name[: -len(".com")]
    # Drop trailing descriptive segments after the brand head when very long.
    if "," in name:
        name = name.split(",", 1)[0].strip()
    return name


@lru_cache(maxsize=1)
def _config_company_names() -> dict[str, str]:
    """Best-effort load of legal names from Structured Narrative company_config."""
    try:
        from company_config import COMPANIES  # type: ignore

        return {
            str(ticker).upper(): str(profile.company_name)
            for ticker, profile in COMPANIES.items()
        }
    except Exception:
        pass

    root = Path(__file__).resolve().parents[3]
    sn_path = root / "Structured Narrative"
    if sn_path.is_dir() and str(sn_path) not in sys.path:
        sys.path.insert(0, str(sn_path))
    try:
        from company_config import COMPANIES  # type: ignore

        return {
            str(ticker).upper(): str(profile.company_name)
            for ticker, profile in COMPANIES.items()
        }
    except Exception:
        return {}


def company_brand(ticker: str) -> str | None:
    """Return a short brand name for *ticker*, or None if unknown."""
    key = str(ticker or "").strip().upper()
    if not key:
        return None
    if key in COMPANY_BRANDS:
        brand = COMPANY_BRANDS[key]
        return None if brand.upper() == key else brand
    legal = _config_company_names().get(key)
    if not legal:
        return None
    short = _shorten_legal_name(legal)
    if not short or short.upper() == key:
        return None
    return short


def format_company_label(ticker: str) -> str:
    """Format ``AAPL`` as ``AAPL (Apple)`` when a brand name is known."""
    key = str(ticker or "").strip().upper()
    if not key:
        return ""
    brand = company_brand(key)
    if not brand:
        return key
    return f"{key} ({brand})"


def with_company_labels(
    rows: list[dict],
    *,
    ticker_key: str = "ticker",
    label_key: str = "company",
) -> list[dict]:
    """Copy rows and add/replace a human company label column."""
    out: list[dict] = []
    for row in rows:
        item = dict(row)
        ticker = item.get(ticker_key)
        if ticker is not None:
            item[label_key] = format_company_label(str(ticker))
        out.append(item)
    return out
