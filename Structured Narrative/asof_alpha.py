#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-sectional forward-return labels, computed offline from cached specific returns.

Two label families share the same T+7 entry-date machinery:
  - "event": anchored at model_date (earnings_date + MODEL_DELAY_DAYS, weekend-rolled).
  - "asof":  anchored at investable_as_of_date (the common cross-ticker T+7 as-of date).

Both are compounded across several forward horizons (HORIZON_WINDOWS) from the same
cached output/{TICKER}/parquet/specific_returns.parquet — no Snowflake access needed
at eval time.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from output_paths import company_artifact, resolve_read_parquet_or_csv  # noqa: E402
from period_dates import model_date_from, to_date  # noqa: E402

# (horizon_key, start_offset_days_excl, end_offset_days_incl, display_name)
# Offsets are calendar days from the shared T+7 entry anchor (model_date for
# event, investable_as_of_date for asof). Boundaries are chosen so consecutive
# windows tile without gaps or double-counting (each window's start offset
# equals the previous window's end offset, matching the exclusive-start /
# inclusive-end rule in compound_specific_return) — mirrors the existing
# single_company_extractor.py ALPHA_WINDOWS = [(0, 60), (60, 90), (0, 90)] pattern.
#
#   T+7  -> T+21 : offsets 0  -> 14
#   T+22 -> T+42 : offsets 14 -> 35
#   T+43 -> T+63 : offsets 35 -> 56
#   T+7  -> T+63 : offsets 0  -> 56  (combined window)
#   legacy 0-90d : offsets 0  -> 90  (kept for continuity with prior results)
HORIZON_WINDOWS: tuple[tuple[str, int, int, str], ...] = (
    ("0_90", 0, 90, "T+7 to ~T+97 (legacy 90d)"),
    ("0_14", 0, 14, "T+7 to T+21"),
    ("14_35", 14, 35, "T+22 to T+42"),
    ("35_56", 35, 56, "T+43 to T+63"),
    ("0_56", 0, 56, "T+7 to T+63 (combined)"),
)

LEGACY_EVENT_WINDOW_KEY = "0_90"


def horizon_display_name(horizon_key: str) -> str:
    for k, _a, _b, name in HORIZON_WINDOWS:
        if k == horizon_key:
            return name
    return horizon_key


def event_alpha_columns(horizon_key: str) -> tuple[str, str, str]:
    return (
        f"alpha_spec_{horizon_key}",
        f"alpha_spec_{horizon_key}_z",
        f"alpha_spec_{horizon_key}_complete",
    )


def asof_alpha_columns(horizon_key: str) -> tuple[str, str, str]:
    return (
        f"alpha_spec_asof_{horizon_key}",
        f"alpha_spec_asof_{horizon_key}_z",
        f"alpha_spec_asof_{horizon_key}_complete",
    )


# Back-compat single-window aliases (existing callers import these directly).
EVENT_ALPHA_COLUMNS = event_alpha_columns(LEGACY_EVENT_WINDOW_KEY)
ASOF_ALPHA_COLUMNS = asof_alpha_columns(LEGACY_EVENT_WINDOW_KEY)

# Full multi-horizon column lists, for callers that want everything.
ALL_EVENT_ALPHA_COLUMNS = [c for k, _a, _b, _n in HORIZON_WINDOWS for c in event_alpha_columns(k)]
ALL_ASOF_ALPHA_COLUMNS = [c for k, _a, _b, _n in HORIZON_WINDOWS for c in asof_alpha_columns(k)]


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


def _model_date_iso(earnings_date) -> str | None:
    d = model_date_from(earnings_date)
    return d.isoformat() if d is not None else None


def apply_multi_horizon_alpha_labels(
    panel: pd.DataFrame,
    *,
    anchor_col: str,
    prefix: str,
    windows: tuple = HORIZON_WINDOWS,
    fetch_if_missing: bool = True,
) -> pd.DataFrame:
    """Compound forward specific returns from ``anchor_col`` for every window in ``windows``.

    Generalizes the single as-of 0-90 window: for each (key, a, b, _name) in
    ``windows``, adds ``{prefix}_{key}``, ``{prefix}_{key}_z``, and
    ``{prefix}_{key}_complete`` columns, all compounded from ``anchor_col`` using
    the same exclusive-start/inclusive-end rule as compound_specific_return
    (window = (anchor + a days, exclusive] to (anchor + b days, inclusive]).
    """
    df = panel.copy()
    for key, _a, _b, _name in windows:
        for col in (f"{prefix}_{key}", f"{prefix}_{key}_z", f"{prefix}_{key}_complete"):
            if col not in df.columns:
                df[col] = None

    if anchor_col not in df.columns or "ticker" not in df.columns:
        return df

    cache: dict[str, pd.DataFrame | None] = {}
    # value_by_key[(ticker, anchor_iso)] -> {window_key: (value, complete)}
    value_by_key: dict[tuple[str, str], dict[str, tuple[float | None, bool]]] = {}

    keys = (
        df[["ticker", anchor_col]]
        .drop_duplicates()
        .itertuples(index=False, name=None)
    )
    for ticker, anchor in keys:
        if pd.isna(anchor) or pd.isna(ticker):
            continue
        t = str(ticker).upper()
        anchor_d = to_date(anchor)
        if anchor_d is None:
            continue
        key = (t, anchor_d.isoformat())
        if t not in cache:
            cache[t] = load_or_fetch_specific_returns(t, fetch_if_missing=fetch_if_missing)
        ret = cache[t]
        start = pd.Timestamp(anchor_d)
        per_window: dict[str, tuple[float | None, bool]] = {}
        for wkey, a, b, _name in windows:
            per_window[wkey] = compound_specific_return(
                ret, start + pd.Timedelta(days=a), start + pd.Timedelta(days=b)
            )
        value_by_key[key] = per_window

    def _lookup(row, wkey: str) -> tuple[float | None, bool]:
        anchor_d = to_date(row.get(anchor_col))
        if anchor_d is None or pd.isna(row.get("ticker")):
            return None, False
        per_window = value_by_key.get((str(row["ticker"]).upper(), anchor_d.isoformat()))
        if per_window is None:
            return None, False
        return per_window.get(wkey, (None, False))

    for wkey, _a, _b, _name in windows:
        looked = df.apply(lambda row: _lookup(row, wkey), axis=1, result_type="expand")
        df[f"{prefix}_{wkey}"] = looked[0]
        df[f"{prefix}_{wkey}_complete"] = looked[1]
        df[f"{prefix}_{wkey}_z"] = _zscore_by_ticker(
            pd.to_numeric(df[f"{prefix}_{wkey}"], errors="coerce"),
            df["ticker"].astype(str).str.upper(),
        )
    return df


def apply_asof_alpha_labels(
    panel: pd.DataFrame,
    *,
    horizon_days: int = 90,
    fetch_if_missing: bool = True,
) -> pd.DataFrame:
    """Add alpha_spec_asof_0_90* using investable_as_of_date as exclusive start.

    Back-compat single-window wrapper around apply_multi_horizon_alpha_labels.
    Prefer apply_asof_multi_horizon_labels to compute the full HORIZON_WINDOWS set.
    """
    window_key = LEGACY_EVENT_WINDOW_KEY if horizon_days == 90 else f"0_{horizon_days}"
    windows = ((window_key, 0, horizon_days, "custom"),)
    return apply_multi_horizon_alpha_labels(
        panel,
        anchor_col="investable_as_of_date",
        prefix="alpha_spec_asof",
        windows=windows,
        fetch_if_missing=fetch_if_missing,
    )


def apply_asof_multi_horizon_labels(
    panel: pd.DataFrame,
    *,
    windows: tuple = HORIZON_WINDOWS,
    fetch_if_missing: bool = True,
) -> pd.DataFrame:
    """Add alpha_spec_asof_{key}* for every horizon in ``windows``."""
    return apply_multi_horizon_alpha_labels(
        panel,
        anchor_col="investable_as_of_date",
        prefix="alpha_spec_asof",
        windows=windows,
        fetch_if_missing=fetch_if_missing,
    )


def apply_event_multi_horizon_labels(
    panel: pd.DataFrame,
    *,
    windows: tuple = HORIZON_WINDOWS,
    fetch_if_missing: bool = True,
    validate_legacy: bool = True,
    validate_tol: float = 1e-6,
) -> pd.DataFrame:
    """Add alpha_spec_{key}* (event, T+7-anchored) forward-return columns for every horizon.

    model_date is not retained in the exported feature panel (build_feature_panel.py
    drops it before writing), so it is recomputed here from earnings_date via
    period_dates.model_date_from — the same T+7 + weekend-roll rule
    single_company_extractor.py used when it originally built alpha_spec_0_90 from
    Snowflake data. The legacy alpha_spec_0_90* triple already on the panel is
    Snowflake-sourced and authoritative; this function leaves it untouched and, when
    validate_legacy is true, only uses the offline recomputation to sanity-check
    that the two pipelines agree (warns on disagreement beyond validate_tol).
    """
    df = panel.copy()
    if "earnings_date" not in df.columns or "ticker" not in df.columns:
        return df

    df["_model_date_offline"] = df["earnings_date"].map(_model_date_iso)

    legacy_cols = event_alpha_columns(LEGACY_EVENT_WINDOW_KEY)
    windows_include_legacy = any(k == LEGACY_EVENT_WINDOW_KEY for k, _a, _b, _n in windows)
    have_legacy = (
        validate_legacy and windows_include_legacy and all(c in df.columns for c in legacy_cols)
    )
    legacy_saved = df[list(legacy_cols)].copy() if have_legacy else None

    df = apply_multi_horizon_alpha_labels(
        df,
        anchor_col="_model_date_offline",
        prefix="alpha_spec",
        windows=windows,
        fetch_if_missing=fetch_if_missing,
    )

    if have_legacy:
        col = legacy_cols[0]
        onfile = pd.to_numeric(legacy_saved[col], errors="coerce")
        offline = pd.to_numeric(df[col], errors="coerce")
        both = onfile.notna() & offline.notna()
        if both.any():
            diff = (onfile[both] - offline[both]).abs()
            n_bad = int((diff > validate_tol).sum())
            if n_bad:
                print(
                    f"Warning: {n_bad}/{int(both.sum())} rows disagree between "
                    f"on-disk (Snowflake) and offline-recomputed alpha_spec_0_90 "
                    f"(max abs diff {float(diff.max()):.6f}); using on-disk values.",
                    file=sys.stderr,
                )
        df[list(legacy_cols)] = legacy_saved

    df = df.drop(columns=["_model_date_offline"], errors="ignore")
    return df


def label_column_sets(mode: str, horizons: list[str] | None = None) -> list[str]:
    """Return label columns for export: event | asof | both, across the given horizons.

    ``horizons`` defaults to every key in HORIZON_WINDOWS. Pass a subset (e.g.
    ``["0_90"]``) to reproduce the legacy single-window behavior.
    """
    mode = (mode or "both").strip().lower()
    if mode not in ("event", "asof", "both"):
        raise ValueError(f"Unknown labels mode {mode!r}; expected event|asof|both")
    keys = horizons if horizons is not None else [k for k, _a, _b, _n in HORIZON_WINDOWS]
    cols: list[str] = []
    if mode in ("event", "both"):
        for k in keys:
            cols.extend(event_alpha_columns(k))
    if mode in ("asof", "both"):
        for k in keys:
            cols.extend(asof_alpha_columns(k))
    return cols
