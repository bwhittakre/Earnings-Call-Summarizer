#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Period-end calendar bucketing and feature availability dates for cross-company panels."""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.market.fiscal_resolver import resolve_quarter_end_date  # noqa: E402

_CALENDAR_QUARTER_END_MONTH = {1: 3, 2: 6, 3: 9, 4: 12}
_MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# T+7 entry-date delay used for both the event alpha anchor (model_date) and the
# as-of investable anchor. Duplicated from single_company_extractor.py's
# MODEL_DELAY_DAYS/model_date_from (rather than imported) so this module — and
# anything that imports it (asof_alpha.py, evaluate_narrative_signals.py) — never
# pulls in single_company_extractor.py's snowflake.connector dependency.
MODEL_DELAY_DAYS = 7


def to_date(val) -> date | None:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    if isinstance(val, date) and not isinstance(val, pd.Timestamp):
        return val
    try:
        return pd.Timestamp(val).date()
    except (TypeError, ValueError):
        return None


def format_us_date(val) -> str:
    d = to_date(val)
    return d.strftime("%m/%d/%Y") if d else ""


def calendar_quarter_from_date(val) -> str | None:
    """Map a period-end date to a compare-mode calendar-quarter bucket.

    Uses the *nearest* calendar quarter-end (Mar 31 / Jun 30 / Sep 30 / Dec 31),
    not the calendar quarter that contains the date. Late-month fiscal ends
    (e.g. NVDA Oct 31 / Jan 31) therefore sit with peers whose periods ended
    ~30 days earlier (Sep 30 / Dec 31), not in the following calendar quarter.
    """
    d = to_date(val)
    if d is None:
        return None
    candidates: list[date] = []
    for year in (d.year - 1, d.year, d.year + 1):
        candidates.extend(
            (
                date(year, 3, 31),
                date(year, 6, 30),
                date(year, 9, 30),
                date(year, 12, 31),
            )
        )
    nearest = min(candidates, key=lambda c: abs((d - c).days))
    q = (nearest.month - 1) // 3 + 1
    return f"{nearest.year}-Q{q}"


def model_date_from(earnings_date) -> date | None:
    """T+7 entry date from an earnings date: +MODEL_DELAY_DAYS calendar days, rolled off weekends.

    Mirrors single_company_extractor.py's model_date_from exactly (same delay,
    same weekend roll-forward rule) so alpha windows recomputed here from cached
    specific_returns line up with the Snowflake-computed alpha_spec_0_90 baked
    into the panel at ingestion time.
    """
    d = to_date(earnings_date)
    if d is None:
        return None
    result = d + timedelta(days=MODEL_DELAY_DAYS)
    while result.weekday() >= 5:
        result += timedelta(days=1)
    return result


def calendar_quarter_sort_key(cq: str) -> tuple[int, int]:
    if not cq or "-Q" not in cq:
        return (0, 0)
    yr, qn = cq.split("-Q", 1)
    return int(yr), int(qn)


def filter_min_calendar_quarter(
    panel: pd.DataFrame,
    min_calendar_quarter: str | None,
) -> pd.DataFrame:
    """Drop rows whose period_end_calendar_quarter is before ``min_calendar_quarter``."""
    if not min_calendar_quarter:
        return panel
    if "period_end_calendar_quarter" not in panel.columns:
        panel = enrich_panel_period_columns(panel)
    floor = calendar_quarter_sort_key(min_calendar_quarter.strip().upper())
    mask = panel["period_end_calendar_quarter"].map(
        lambda cq: calendar_quarter_sort_key(str(cq)) >= floor if pd.notna(cq) else False
    )
    return panel.loc[mask].copy()


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


def _iso(d: date | None) -> str | None:
    return d.isoformat() if d is not None else None


def row_call_feature_available_date(row: pd.Series) -> str | None:
    """Availability for call-date features (level/delta/surprise/novelty/quant_z_pit)."""
    for col in ("as_of_date", "earnings_date"):
        if pd.notna(row.get(col)):
            d = to_date(row.get(col))
            return _iso(d) if d is not None else str(row.get(col))
    return None


def row_t7_feature_available_date(row: pd.Series) -> str | None:
    """Availability for quant_guidance_revision_z_pit; null when revision absent."""
    if pd.isna(row.get("quant_guidance_revision_z_pit")):
        return None
    md = row.get("model_date")
    if pd.notna(md):
        d = to_date(md)
        return _iso(d) if d is not None else str(md)
    earn = to_date(row.get("earnings_date"))
    if earn is not None:
        return (earn + timedelta(days=7)).isoformat()
    return None


def row_feature_availability_date(row: pd.Series) -> str | None:
    """Compat/display: earliest call-date feature availability (not T+7)."""
    return row_call_feature_available_date(row)


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
    if "earnings_date" in df.columns:
        # Event-label walk-forward grouping key: fiscal_period labels aren't
        # calendar-aligned across companies, so bucket by the nearest calendar
        # quarter-end of the *earnings date* itself (same nearest-quarter-end
        # rule as period_end_calendar_quarter, applied to a different date).
        df["earnings_date_calendar_quarter"] = df["earnings_date"].map(calendar_quarter_from_date)
    return df


def apply_feature_availability_dates(panel: pd.DataFrame) -> pd.DataFrame:
    """Set call/T+7 feature-level availability and compat feature_availability_date."""
    df = panel.copy()
    df["call_feature_available_date"] = df.apply(row_call_feature_available_date, axis=1)
    df["t7_feature_available_date"] = df.apply(row_t7_feature_available_date, axis=1)
    df["feature_availability_date"] = df["call_feature_available_date"]
    return df


def _event_t7_date(row: pd.Series) -> date | None:
    """Per-event T+7 entry date: model_date when present, else earnings+7."""
    md = to_date(row.get("model_date"))
    if md is not None:
        return md
    t7 = to_date(row.get("t7_feature_available_date"))
    if t7 is not None:
        return t7
    earn = to_date(row.get("earnings_date"))
    if earn is not None:
        return earn + timedelta(days=7)
    return None


def apply_investable_cross_section_columns(panel: pd.DataFrame) -> pd.DataFrame:
    """Add common as-of date, age columns, and investable_ready within calendar-quarter buckets.

    investable_as_of_date = T+7 after the latest earnings_date in the bucket
    (or the latest model_date / event T+7 when available).
    """
    df = panel.copy()
    if "period_end_calendar_quarter" not in df.columns:
        df = enrich_panel_period_columns(df)
    if "call_feature_available_date" not in df.columns:
        df = apply_feature_availability_dates(df)

    as_of_by_bucket: dict[str, date | None] = {}
    for bucket, grp in df.groupby("period_end_calendar_quarter", dropna=False):
        if pd.isna(bucket):
            as_of_by_bucket[str(bucket)] = None
            continue
        event_dates: list[date] = []
        # One event date per ticker×fiscal_period
        keys = [c for c in ("ticker", "fiscal_period") if c in grp.columns]
        if keys:
            for _, eg in grp.groupby(keys, sort=False):
                d = _event_t7_date(eg.iloc[0])
                if d is not None:
                    event_dates.append(d)
        else:
            for _, row in grp.iterrows():
                d = _event_t7_date(row)
                if d is not None:
                    event_dates.append(d)
        as_of_by_bucket[str(bucket)] = max(event_dates) if event_dates else None

    def _as_of(row) -> str | None:
        bucket = row.get("period_end_calendar_quarter")
        d = as_of_by_bucket.get(str(bucket) if pd.notna(bucket) else "")
        return _iso(d)

    df["investable_as_of_date"] = df.apply(_as_of, axis=1)

    def _days_since_earnings(row) -> int | None:
        as_of = to_date(row.get("investable_as_of_date"))
        earn = to_date(row.get("earnings_date"))
        if as_of is None or earn is None:
            return None
        return (as_of - earn).days

    def _feature_age(row) -> int | None:
        as_of = to_date(row.get("investable_as_of_date"))
        if as_of is None:
            return None
        # Delayed revision feature: age from T+7 availability when present
        if pd.notna(row.get("quant_guidance_revision_z_pit")) and pd.notna(
            row.get("t7_feature_available_date")
        ):
            avail = to_date(row.get("t7_feature_available_date"))
        else:
            avail = to_date(row.get("call_feature_available_date"))
        if avail is None:
            return None
        return (as_of - avail).days

    def _investable_ready(row) -> bool:
        as_of = to_date(row.get("investable_as_of_date"))
        if as_of is None:
            return False
        call = to_date(row.get("call_feature_available_date"))
        if call is not None and call > as_of:
            return False
        if pd.notna(row.get("quant_guidance_revision_z_pit")):
            t7 = to_date(row.get("t7_feature_available_date"))
            if t7 is not None and t7 > as_of:
                return False
        return True

    df["days_since_earnings"] = df.apply(_days_since_earnings, axis=1)
    df["feature_age_days"] = df.apply(_feature_age, axis=1)
    df["investable_ready"] = df.apply(_investable_ready, axis=1)
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
    call_avail = format_us_date(
        row.get("call_feature_available_date") or row.get("feature_availability_date")
    )
    if call_avail:
        parts.append(f'<div class="fp-sub">Call features {call_avail}</div>')
    t7_avail = format_us_date(row.get("t7_feature_available_date"))
    if t7_avail:
        parts.append(f'<div class="fp-sub">T+7 revision {t7_avail}</div>')
    asof = format_us_date(row.get("investable_as_of_date"))
    if asof:
        parts.append(f'<div class="fp-sub">Investable as-of {asof}</div>')
    age = row.get("feature_age_days")
    if age is not None and pd.notna(age):
        parts.append(f'<div class="fp-sub">Feature age {int(age)}d</div>')
    return "".join(parts)


def period_end_sort_columns() -> list[str]:
    """Leading sort keys before thematic dimension order (see dimension_order.py)."""
    return ["period_end_date", "ticker", "fiscal_period"]
