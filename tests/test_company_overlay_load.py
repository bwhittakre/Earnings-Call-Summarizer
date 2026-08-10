"""get_company lazy-loads on-disk company overlays for subprocess scoring."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SN = REPO / "Structured Narrative"
if str(SN) not in sys.path:
    sys.path.insert(0, str(SN))

from company_config import (  # noqa: E402
    COMPANIES,
    get_company,
    load_company_overlay,
)


def _write_overlay(directory: Path, ticker: str, **fields) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    payload = {
        "ticker": ticker.upper(),
        "company_name": fields.get("company_name", f"{ticker.upper()} Test Co"),
        "estpermid": fields.get("estpermid", 111),
        "isin": fields.get("isin", "US0000000001"),
        "barra_id": fields.get("barra_id", "USTEST01"),
        "prior_quarters": fields.get("prior_quarters", ["FY2024-Q3"]),
        "output_quarters": fields.get(
            "output_quarters", ["FY2024-Q4", "FY2025-Q1"]
        ),
        "updated_at": "2026-08-10T00:00:00+00:00",
    }
    path = directory / f"{ticker.upper()}.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def test_load_company_overlay_missing_returns_none(tmp_path: Path):
    assert load_company_overlay("NOSUCH", overlay_dir=tmp_path) is None


def test_get_company_overlay_only_ticker(tmp_path: Path):
    ticker = "ZZOVLY"
    COMPANIES.pop(ticker, None)
    _write_overlay(
        tmp_path,
        ticker,
        company_name="Overlay Only Inc",
        estpermid=999001,
        output_quarters=["FY2025-Q1", "FY2025-Q2"],
    )
    try:
        profile = get_company(ticker, overlay_dir=tmp_path)
        assert profile.ticker == ticker
        assert profile.company_name == "Overlay Only Inc"
        assert profile.estpermid == 999001
        assert profile.output_quarters == ("FY2025-Q1", "FY2025-Q2")
        assert COMPANIES[ticker] is profile
    finally:
        COMPANIES.pop(ticker, None)


def test_get_company_overlay_overrides_hardcoded(tmp_path: Path):
    assert "AMZN" in COMPANIES
    original = COMPANIES["AMZN"]
    _write_overlay(
        tmp_path,
        "AMZN",
        company_name="Amazon Overlay",
        estpermid=42,
        isin="US0231351067",
        barra_id="USAXO31",
        prior_quarters=["FY2020-Q1"],
        output_quarters=["FY2020-Q2", "FY2020-Q3"],
    )
    try:
        profile = get_company("AMZN", overlay_dir=tmp_path)
        assert profile.company_name == "Amazon Overlay"
        assert profile.estpermid == 42
        assert profile.prior_quarters == ("FY2020-Q1",)
        assert profile.output_quarters == ("FY2020-Q2", "FY2020-Q3")
    finally:
        COMPANIES["AMZN"] = original


def test_get_company_unknown_without_overlay_raises(tmp_path: Path):
    ticker = "ZZMISS"
    COMPANIES.pop(ticker, None)
    with pytest.raises(KeyError, match=ticker):
        get_company(ticker, overlay_dir=tmp_path)


def test_get_company_caches_after_overlay_removed(tmp_path: Path):
    ticker = "ZZCACHE"
    COMPANIES.pop(ticker, None)
    path = _write_overlay(tmp_path, ticker, estpermid=555)
    try:
        first = get_company(ticker, overlay_dir=tmp_path)
        assert first.estpermid == 555
        path.unlink()
        second = get_company(ticker, overlay_dir=tmp_path)
        assert second.estpermid == 555
        assert second is COMPANIES[ticker]
    finally:
        COMPANIES.pop(ticker, None)
