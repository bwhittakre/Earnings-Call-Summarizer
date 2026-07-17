#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Period-end calendar bucketing and feature availability dates for cross-company panels."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.market.fiscal_resolver import resolve_quarter_end_date  # noqa: E402

_CALENDAR_QUARTER_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}
_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def to_date(val) -> date | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, date):
        return val
    try:
        return pd.Timestamp(val).date()
    except (TypeError, ValueError):
        return None


def format_us_date(val) -> str:
    d = to_date(val)
    return d.strftime("%m/%d/%Y") if d else ""


def calendar_quarter_from_date(val) -> str | None:
    d = to_date(val)
    if d is None:
        return None
    q = (d.month - 1) // 3 + 1
    return f"{d.year}-Q{q}"


def calendar_quarter_sort_key(cq: str) -> tuple[int, int]:
    if not cq or "-Q" not in cq:
        return (0, 0)
    yr, qn = cq.split("-Q", 1)
    return int(yr), int(qn)


def calendar_quarter_display(cq: str) -> str:
    """Human label for compare-mode bucket buttons."""
    if not cq or "-Q" not in cq:
        return cq or ""
    yr, qn = cq.split("-Q", 1)
    q = int(qn)
    start_month = (q - 1) * 3 + 1
    end_month = _CALENDAR_QUARTER_END_MONTH[q]
    return f"Periods ending {_MONTH_ABBR[start_month - 1]}–{_MONTH_ABBR[end_month - 1]} {yr}"


def resolve_period_end_date(
    ticker: str,
    fiscal_period: str,
    *,
    raw_value=None,
) -> date | None:
    d = to_date(raw_value)
    if d is not None:
        return d
    try:
        return resolve_quarter_end_date(ticker.strip().upper(), fiscal_period)
    except Exception:
        return None


def row_feature_availability_date(row: pd.Series) -> str | None:
    """PIT availability: call date for most dims; T+7 / model_date for guidance revision z."""
    dim = row.get("dimension")
    rev_z = row.get("quant_guidance_revision_z_pit")
    if dim == "guidance" and pd.notna(rev_z):
        md = row.get("model_date")
        if pd.notna(md):
            return str(to_date(md) or md)
        earn = to_date(row.get("earnings_date"))
        if earn is not None:
            return (pd.Timestamp(earn) + pd.Timedelta(days=7)).date().isoformat()
    for col in ("as_of_date", "earnings_date"):
        if pd.notna(row.get(col)):
            return str(row.get(col))
    return None


def enrich_panel_period_columns(panel: pd.DataFrame) -> pd.DataFrame:
    """Ensure period_end_date and period_end_calendar_quarter exist on every row."""
    df = panel.copy()
    if "period_end_date" not in df.columns:
        df["period_end_date"] = None

    lookups: dict[tuple[str, str], date | None] = {}
    for (ticker, fp), grp in df.groupby(["ticker", "fiscal_period"], sort=False):
        raw = grp["period_end_date"].dropna()
        if not raw.empty:
            lookups[(str(ticker), str(fp))] = to_date(raw.iloc[0])
        else:
            fiscal_qe = grp.get("fiscal_quarter_end")
            raw2 = fiscal_qe.dropna() if fiscal_qe is not None else pd.Series(dtype=object)
            if len(raw2):
                lookups[(str(ticker), str(fp))] = resolve_period_end_date(
                    str(ticker), str(fp), raw_value=raw2.iloc[0]
                )
            else:
                lookups[(str(ticker), str(fp))] = resolve_period_end_date(str(ticker), str(fp))

    def _ped(row):
        key = (str(row["ticker"]), str(row["fiscal_period"]))
        d = lookups.get(key)
        return d.isoformat() if d else None

    df["period_end_date"] = df.apply(_ped, axis=1)
    df["period_end_calendar_quarter"] = df["period_end_date"].map(calendar_quarter_from_date)
    return df


def apply_feature_availability_dates(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.copy()
    df["feature_availability_date"] = df.apply(row_feature_availability_date, axis=1)
    return df


def quarter_cell_html(row: pd.Series) -> str:
    """Multi-line quarter label for HTML tables."""
    fp = row.get("fiscal_period", "")
    parts = [f'<div class="fp-label">{fp}</div>']
    ped = format_us_date(row.get("period_end_date"))
    if ped:
        parts.append(f'<div class="fp-sub">Period ending {ped}</div>')
    ecall = format_us_date(row.get("earnings_date"))
    if ecall:
        parts.append(f'<div class="fp-sub">Earnings call {ecall}</div>')
    avail = format_us_date(row.get("feature_availability_date"))
    if avail and avail != ecall:
        parts.append(f'<div class="fp-sub">Feature available {avail}</div>')
    return "".join(parts)


def period_end_sort_columns() -> list[str]:
    """Leading sort keys before thematic dimension order (see dimension_order.py)."""
    return ["period_end_date", "ticker", "fiscal_period"]
