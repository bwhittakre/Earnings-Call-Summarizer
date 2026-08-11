"""Pure Narrative-vs-Quant analytics helpers (Streamlit-free)."""

from __future__ import annotations

import math
import re
from statistics import median
from typing import Any, Mapping, MutableMapping, Sequence

_PERIOD_RE = re.compile(r"^FY(\d{4})-Q([1-4])$", re.IGNORECASE)
_CALENDAR_RE = re.compile(r"^(\d{4})-Q([1-4])$", re.IGNORECASE)


def period_sort_key(value: Any) -> tuple[int, int, str]:
    """Thin fiscal/calendar quarter sort key (avoids importing data.py)."""
    text = str(value or "")
    match = _PERIOD_RE.match(text) or _CALENDAR_RE.match(text)
    if match:
        return (int(match.group(1)), int(match.group(2)), text)
    return (10**9, 9, text)


def point_calendar_quarter(point: Mapping[str, Any]) -> str:
    """Calendar bucket for a point; falls back to fiscal_period when missing."""
    calendar = point.get("calendar_quarter")
    if calendar not in (None, ""):
        return str(calendar)
    return str(point.get("fiscal_period") or "")


def calendar_quarter_options(points: Sequence[Mapping[str, Any]]) -> list[str]:
    """Unique calendar quarters from loaded points, sorted chronologically."""
    return sorted(
        {point_calendar_quarter(point) for point in points if point_calendar_quarter(point)},
        key=period_sort_key,
    )


def filter_by_calendar_quarters(
    points: Sequence[Mapping[str, Any]],
    selected: Sequence[str] | None,
) -> list[dict[str, Any]]:
    """Keep points whose calendar_quarter is in ``selected``.

    Empty ``selected`` with non-empty options yields no rows (explicit deselect).
    Empty options leaves points unchanged.
    """
    options = calendar_quarter_options(points)
    if not options:
        return [dict(point) for point in points]
    if selected is None:
        return [dict(point) for point in points]
    wanted = {str(item) for item in selected}
    return [
        dict(point)
        for point in points
        if point_calendar_quarter(point) in wanted
    ]


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _quarters_adjacent(prev: str, curr: str) -> bool:
    prev_key = period_sort_key(prev)
    curr_key = period_sort_key(curr)
    if prev_key[0] >= 10**9 or curr_key[0] >= 10**9:
        return False
    prev_year, prev_q, _ = prev_key
    curr_year, curr_q, _ = curr_key
    if prev_q == 4:
        return curr_year == prev_year + 1 and curr_q == 1
    return curr_year == prev_year and curr_q == prev_q + 1


def point_key(point: Mapping[str, Any]) -> str:
    ticker = str(point.get("ticker") or "").upper()
    period = str(point.get("fiscal_period") or "")
    dimension = str(point.get("dimension") or "")
    return f"{ticker}|{period}|{dimension}"


def compute_agreement_streaks(
    points: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Annotate diverge/align streaks and agreement flips per ticker×dimension.

    Ordering and adjacency use calendar_quarter (fiscal fallback). Missing
    calendar quarters between observations break the streak.
    ``agreement_flipped`` compares to the prior observation in sort order.
    """
    enriched = [dict(point) for point in points]
    enriched.sort(
        key=lambda row: (
            str(row.get("ticker") or "").upper(),
            str(row.get("dimension") or ""),
            period_sort_key(point_calendar_quarter(row)),
        )
    )
    prev_by_series: dict[tuple[str, str], dict[str, Any]] = {}
    for row in enriched:
        ticker = str(row.get("ticker") or "").upper()
        dimension = str(row.get("dimension") or "")
        series = (ticker, dimension)
        agreement = str(row.get("agreement") or "")
        if not agreement:
            agreement = (
                "Divergence" if bool(row.get("divergence")) else "Aligned"
            )
            row["agreement"] = agreement
        prior = prev_by_series.get(series)
        diverge_streak = 1 if agreement == "Divergence" else 0
        align_streak = 1 if agreement == "Aligned" else 0
        flipped = False
        if prior is not None:
            prior_q = point_calendar_quarter(prior)
            curr_q = point_calendar_quarter(row)
            adjacent = _quarters_adjacent(prior_q, curr_q)
            prior_agreement = str(prior.get("agreement") or "")
            flipped = prior_agreement != agreement
            if adjacent and prior_agreement == agreement:
                if agreement == "Divergence":
                    diverge_streak = int(prior.get("diverge_streak") or 0) + 1
                else:
                    align_streak = int(prior.get("align_streak") or 0) + 1
        row["agreement_flipped"] = bool(flipped)
        row["diverge_streak"] = int(diverge_streak)
        row["align_streak"] = int(align_streak)
        prev_by_series[series] = row
    return enriched


def compute_peer_gap_deltas(
    points: Sequence[Mapping[str, Any]],
    peer_universe_points: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach peer median gap / delta / n by calendar_quarter × dimension."""
    buckets: dict[tuple[str, str], list[float]] = {}
    for peer in peer_universe_points:
        gap = _finite(peer.get("gap"))
        if gap is None:
            continue
        key = (point_calendar_quarter(peer), str(peer.get("dimension") or ""))
        buckets.setdefault(key, []).append(gap)

    medians: dict[tuple[str, str], tuple[float, int]] = {}
    for key, values in buckets.items():
        medians[key] = (float(median(values)), len(values))

    enriched: list[dict[str, Any]] = []
    for point in points:
        row = dict(point)
        key = (point_calendar_quarter(row), str(row.get("dimension") or ""))
        peer_median, peer_n = medians.get(key, (None, 0))
        row["peer_gap_median"] = (
            round(peer_median, 6) if peer_median is not None else None
        )
        row["peer_n"] = int(peer_n)
        gap = _finite(row.get("gap"))
        if gap is None or peer_median is None:
            row["peer_gap_delta"] = None
        else:
            row["peer_gap_delta"] = round(gap - peer_median, 6)
        enriched.append(row)
    return enriched
