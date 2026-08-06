"""Load Bloomberg-style 1-minute OHLC+volume bars; localize naive ET -> UTC."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

BAR_TZ = "America/New_York"

# Bloomberg exports often append series labels to Volume.
_VOLUME_ALIASES = (
    "volume",
    "amzn us equity - volume",
    "vol",
)


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(c).strip() for c in out.columns]
    lower_map = {c.lower(): c for c in out.columns}

    def pick(*names: str) -> str | None:
        for name in names:
            if name in lower_map:
                return lower_map[name]
        return None

    date_col = pick("date", "datetime", "time", "timestamp")
    if date_col is None:
        raise ValueError(f"No Date/time column in bars; columns={list(out.columns)}")

    open_col = pick("open")
    high_col = pick("high")
    low_col = pick("low")
    close_col = pick("close", "last", "px_last")
    if close_col is None:
        raise ValueError(f"No Close/Last column in bars; columns={list(out.columns)}")

    volume_col = None
    for alias in _VOLUME_ALIASES:
        if alias in lower_map:
            volume_col = lower_map[alias]
            break
    if volume_col is None:
        for key, original in lower_map.items():
            if "volume" in key and "smavg" not in key:
                volume_col = original
                break

    rename: dict[str, str] = {date_col: "ts_raw", close_col: "close"}
    if open_col:
        rename[open_col] = "open"
    if high_col:
        rename[high_col] = "high"
    if low_col:
        rename[low_col] = "low"
    if volume_col:
        rename[volume_col] = "volume"

    slim = out.rename(columns=rename)
    keep = [c for c in ("ts_raw", "open", "high", "low", "close", "volume") if c in slim.columns]
    slim = slim[keep].copy()
    # Drop SMAVG / helper columns implicitly by only keeping OHLC+volume.
    return slim


def load_bars(
    path: Path | str,
    *,
    assume_tz: str = BAR_TZ,
) -> pd.DataFrame:
    """
    Return minute bars indexed ascending in UTC.

    Columns: open/high/low/close/volume (volume optional), plus ts_utc.
    Naive Excel timestamps are treated as ``assume_tz`` (default America/New_York).
    """
    path = Path(path)
    raw = pd.read_excel(path)
    if raw.empty:
        raise ValueError(f"Bars file is empty: {path}")

    slim = _normalize_columns(raw)
    ts = pd.to_datetime(slim["ts_raw"], errors="coerce")
    if ts.isna().all():
        raise ValueError(f"Could not parse Date column in {path}")

    # Bloomberg often exports newest-first; always sort ascending.
    was_reverse = bool(len(ts) >= 2 and ts.iloc[0] > ts.iloc[-1])

    if getattr(ts.dt, "tz", None) is None:
        ts = ts.dt.tz_localize(assume_tz, ambiguous="infer", nonexistent="shift_forward")
    ts_utc = ts.dt.tz_convert("UTC")

    out = slim.drop(columns=["ts_raw"]).copy()
    out.insert(0, "ts_utc", ts_utc)
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["ts_utc", "close"]).sort_values("ts_utc").reset_index(drop=True)
    out.attrs["assumed_tz"] = assume_tz
    out.attrs["sorted_from_reverse"] = was_reverse
    out.attrs["source_path"] = str(path)
    return out


def bars_meta(bars: pd.DataFrame) -> dict[str, Any]:
    if bars.empty:
        return {
            "bar_count": 0,
            "ts_start_utc": None,
            "ts_end_utc": None,
            "assumed_tz": bars.attrs.get("assumed_tz"),
            "sorted_from_reverse": bars.attrs.get("sorted_from_reverse"),
            "source_path": bars.attrs.get("source_path"),
        }
    return {
        "bar_count": int(len(bars)),
        "ts_start_utc": bars["ts_utc"].iloc[0].isoformat(),
        "ts_end_utc": bars["ts_utc"].iloc[-1].isoformat(),
        "assumed_tz": bars.attrs.get("assumed_tz", BAR_TZ),
        "sorted_from_reverse": bool(bars.attrs.get("sorted_from_reverse", False)),
        "source_path": bars.attrs.get("source_path"),
        "has_volume": "volume" in bars.columns,
    }
