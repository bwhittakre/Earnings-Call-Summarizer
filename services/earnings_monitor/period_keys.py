"""Shared FY / conference period identity for scorecard, briefs, and desk UI.

``canonical_period`` maps a conference stamp onto a calendar FY quarter and is
only for delivery rolling math. Row keys and brief pickers use the raw label
(``FY2026-Q2`` or ``CONF-2025-08-27``).
"""
from __future__ import annotations

import re
from datetime import date

_FY_RE = re.compile(r"^FY(\d{4})-Q([1-4])$", re.IGNORECASE)
_CONF_RE = re.compile(r"^CONF-(\d{4})-(\d{2})-(\d{2})$", re.IGNORECASE)

_QTR_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


def period_kind(fp: str | None) -> str:
    """Return ``fy``, ``conf``, or ``unknown``."""
    text = str(fp or "").strip()
    if _CONF_RE.fullmatch(text):
        return "conf"
    if _FY_RE.fullmatch(text):
        return "fy"
    return "unknown"


def canonical_period(fp: str | None) -> str:
    """Map ``CONF-YYYY-MM-DD`` onto ``FY{year}-Q{quarter}``; leave FY labels alone."""
    text = str(fp or "").strip()
    match = _CONF_RE.fullmatch(text)
    if match:
        year = int(match.group(1))
        month = int(match.group(2))
        quarter = (month - 1) // 3 + 1
        return f"FY{year}-Q{quarter}"
    return text


def fiscal_key(fp: str | None) -> tuple[int, int]:
    """Canonical (year, quarter) for delivery / age math. Unknown → (0, 0)."""
    match = _FY_RE.fullmatch(canonical_period(fp))
    if match:
        return (int(match.group(1)), int(match.group(2)))
    return (0, 0)


def period_sort_key(fp: str | None) -> tuple[int, int, int, int]:
    """Sort FY quarters first (by year/q), then conferences by date."""
    text = str(fp or "").strip()
    fy = _FY_RE.fullmatch(text)
    if fy:
        return (0, int(fy.group(1)), int(fy.group(2)), 0)
    conf = _CONF_RE.fullmatch(text)
    if conf:
        return (1, int(conf.group(1)), int(conf.group(2)), int(conf.group(3)))
    return (2, 0, 0, 0)


def call_chrono_key(fp: str | None) -> date:
    """Interleave earnings and conferences on a calendar timeline.

    Conferences use the event date. FY quarters use quarter-end as a proxy
    for the earnings window so the scorecard chart can mix both kinds.
    """
    text = str(fp or "").strip()
    if period_kind(text) == "conf":
        day = conf_date(text)
        if day is not None:
            return day
    end = quarter_end_date(text)
    if end is not None:
        return end
    return date.min


def period_label(fp: str | None, event_name: str | None = None) -> str:
    """Human label. Conferences keep the date and optional event title."""
    text = str(fp or "").strip()
    if period_kind(text) == "conf":
        day = text[5:]
        if event_name:
            return f"{event_name} ({day})"
        return f"Conference {day}"
    return text or "—"


def conf_date(fp: str | None) -> date | None:
    match = _CONF_RE.fullmatch(str(fp or "").strip())
    if not match:
        return None
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def quarter_end_date(fp: str | None) -> date | None:
    year, quarter = fiscal_key(fp)
    if (year, quarter) == (0, 0):
        return None
    month, day = _QTR_END[quarter]
    return date(year, month, day)


def seed_before_call(seed_fp: str | None, call_fp: str | None) -> bool:
    """True when the seed was introduced strictly before this call."""
    call = str(call_fp or "").strip()
    seed = str(seed_fp or "").strip()
    if not seed or not call:
        return False
    if period_kind(call) == "conf":
        call_day = conf_date(call)
        if call_day is None:
            return False
        if period_kind(seed) == "conf":
            seed_day = conf_date(seed)
            return seed_day is not None and seed_day < call_day
        end = quarter_end_date(seed)
        return end is not None and end < call_day
    return fiscal_key(seed) < fiscal_key(call)
