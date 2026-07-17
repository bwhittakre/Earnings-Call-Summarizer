#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-sectional forward-return labels starting at investable_as_of_date."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from output_paths import company_artifact, resolve_read_parquet_or_csv  # noqa: E402
from period_dates import to_date  # noqa: E402

ASOF_ALPHA_COLUMNS = (
    "alpha_spec_asof_0_90",
    "alpha_spec_asof_0_90_z",
    "alpha_spec_asof_0_90_complete",
)

EVENT_ALPHA_COLUMNS = (
    "alpha_spec_0_90",
    "alpha_spec_0_90_z",
    "alpha_spec_0_90_complete",
)


def compound_specific_return(
    ret: pd.DataFrame,
    start_excl,
    end_incl,
) -> tuple[float | None, bool]:
    """Compound specific returns with exclusive start and inclusive end."""
    if ret is None or ret.empty:
        return None, False
    start_excl = pd.Timestamp(start_excl).normalize()
    end_incl = pd.Timestamp(end_incl).normalize()
    dates = pd.to_datetime(ret["date_of_data"])
    if dates.max() < end_incl:
        return None, False
    w = ret[(dates > start_excl) & (dates <= end_incl)]
    if w.empty:
        return None, False
    return float((1.0 + w["specific_return"] / 100.0).prod() - 1.0), True


def returns_cache_path(ticker: str) -> Path:
    return company_artifact(ticker, "parquet", "specific_returns", "parquet", mkdir=True)


def save_specific_returns(ticker: str, ret: pd.DataFrame) -> Path:
    """Persist daily specific returns for offline as-of alpha compounding."""
    out = ret.copy()
    out["date_of_data"] = pd.to_datetime(out["date_of_data"])
    out["specific_return"] = pd.to_numeric(out["specific_return"], errors="coerce")
    out = out.dropna(subset=["date_of_data", "specific_return"]).sort_values("date_of_data")
    path = returns_cache_path(ticker)
    out[["date_of_data", "specific_return"]].to_parquet(path, index=False)
    return path


def load_specific_returns(ticker: str) -> pd.DataFrame | None:
    path = resolve_read_parquet_or_csv(ticker, "specific_returns", layer="parquet")
    if path is None:
        return None
    df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
    df["date_of_data"] = pd.to_datetime(df["date_of_data"])
    df["specific_return"] = pd.to_numeric(df["specific_return"], errors="coerce")
    return df.dropna(subset=["date_of_data", "specific_return"]).sort_values("date_of_data")


def fetch_and_cache_specific_returns(ticker: str) -> pd.DataFrame | None:
    """Pull returns from Snowflake and cache; return None if unavailable."""
    try:
        from single_company_extractor import (  # noqa: WPS433
            connect,
            pull_returns,
            resolve_dbs,
        )
        from company_config import get_company, resolve_company_ids
    except Exception:
        return None

    try:
        company = get_company(ticker)
        conn = connect()
        cur = conn.cursor()
        company = resolve_company_ids(cur, company)
        _lseg, msci = resolve_dbs(cur)
        ret = pull_returns(cur, msci, company)
        cur.close()
        conn.close()
        if ret is None or ret.empty:
            return None
        save_specific_returns(ticker, ret)
        return load_specific_returns(ticker)
    except Exception as exc:
        print(f"  ! asof alpha: could not fetch returns for {ticker}: {exc}", file=sys.stderr)
        return None


def load_or_fetch_specific_returns(ticker: str, *, fetch_if_missing: bool = True) -> pd.DataFrame | None:
    cached = load_specific_returns(ticker)
    if cached is not None and not cached.empty:
        return cached
    if fetch_if_missing:
        return fetch_and_cache_specific_returns(ticker)
    return None


def _zscore_by_ticker(series: pd.Series, ticker: pd.Series) -> pd.Series:
    out = pd.Series(np.nan, index=series.index, dtype=float)
    for t, idx in ticker.groupby(ticker).groups.items():
        vals = series.loc[idx]
        mu = vals.mean(skipna=True)
        sd = vals.std(skipna=True, ddof=0)
        if pd.isna(sd) or sd == 0:
            out.loc[idx] = np.nan
        else:
            out.loc[idx] = (vals - mu) / sd
    return out


def apply_asof_alpha_labels(
    panel: pd.DataFrame,
    *,
    horizon_days: int = 90,
    fetch_if_missing: bool = True,
) -> pd.DataFrame:
    """Add alpha_spec_asof_0_90* using investable_as_of_date as exclusive start."""
    df = panel.copy()
    for col in ASOF_ALPHA_COLUMNS:
        if col not in df.columns:
            df[col] = None

    if "investable_as_of_date" not in df.columns or "ticker" not in df.columns:
        return df

    cache: dict[str, pd.DataFrame | None] = {}
    value_by_key: dict[tuple[str, str], tuple[float | None, bool]] = {}

    keys = (
        df[["ticker", "investable_as_of_date"]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    for ticker, asof in keys:
        if pd.isna(asof) or pd.isna(ticker):
            continue
        t = str(ticker).upper()
        asof_d = to_date(asof)
        if asof_d is None:
            continue
        key = (t, asof_d.isoformat())
        if t not in cache:
            cache[t] = load_or_fetch_specific_returns(t, fetch_if_missing=fetch_if_missing)
        ret = cache[t]
        start = pd.Timestamp(asof_d)
        end = start + pd.Timedelta(days=horizon_days)
        value_by_key[key] = compound_specific_return(ret, start, end)

    def _lookup(row) -> tuple[float | None, bool]:
        asof_d = to_date(row.get("investable_as_of_date"))
        if asof_d is None or pd.isna(row.get("ticker")):
            return None, False
        return value_by_key.get((str(row["ticker"]).upper(), asof_d.isoformat()), (None, False))

    looked = df.apply(_lookup, axis=1, result_type="expand")
    df["alpha_spec_asof_0_90"] = looked[0]
    df["alpha_spec_asof_0_90_complete"] = looked[1]
    df["alpha_spec_asof_0_90_z"] = _zscore_by_ticker(
        pd.to_numeric(df["alpha_spec_asof_0_90"], errors="coerce"),
        df["ticker"].astype(str).str.upper(),
    )
    return df


def label_column_sets(mode: str) -> list[str]:
    """Return label columns for export: event | asof | both."""
    mode = (mode or "both").strip().lower()
    if mode == "event":
        return list(EVENT_ALPHA_COLUMNS)
    if mode == "asof":
        return list(ASOF_ALPHA_COLUMNS)
    if mode == "both":
        return list(EVENT_ALPHA_COLUMNS) + list(ASOF_ALPHA_COLUMNS)
    raise ValueError(f"Unknown labels mode {mode!r}; expected event|asof|both")
