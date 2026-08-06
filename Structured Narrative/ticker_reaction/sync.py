"""Timing sync contract, join-health diagnostics, and lag sensitivity sweep."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import numpy as np
import pandas as pd

from ticker_reaction.align import AlignedUtterance, utterance_wall_clock
from ticker_reaction.load_bars import BAR_TZ
from ticker_reaction.load_transcript import EventAnchors, TimedTranscript

LAG_SWEEP_SECONDS = (-60, -30, 0, 30, 60)
MATCH_RATE_SUSPECT = 0.95
P95_ABS_LAG_SUSPECT_SEC = 45.0
FRAGILE_JACCARD_30S = 0.5


def _to_utc_ts(dt: datetime | None) -> pd.Timestamp | None:
    if dt is None:
        return None
    ts = pd.Timestamp(dt)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def sync_contract(
    anchors: EventAnchors,
    *,
    call_end: datetime | None = None,
    timing_lag_sec: float = 0.0,
) -> dict[str, Any]:
    return {
        "bars_tz_assumed": BAR_TZ,
        "call_at": anchors.call_at.isoformat(),
        "report_at": anchors.report_at.isoformat() if anchors.report_at else None,
        "call_end": call_end.isoformat() if call_end else None,
        "utterance_clock": "call_at + start_sec + timing_lag_sec",
        "bar_match_rule": "nearest bar within 60 seconds",
        "quartr_zero_meaning": "seconds from call/audio start (assumed)",
        "timing_lag_sec": float(timing_lag_sec),
    }


def join_health(
    aligned: list[AlignedUtterance],
) -> dict[str, Any]:
    if not aligned:
        return {
            "match_rate": None,
            "matched_count": 0,
            "unmatched_count": 0,
            "median_abs_lag_sec": None,
            "p95_abs_lag_sec": None,
            "signed_lag_sec": [],
            "lag_histogram": {},
            "no_bar_within_60s": 0,
            "sync_suspect": True,
        }

    signed: list[float] = []
    abs_lags: list[float] = []
    matched = 0
    for u in aligned:
        if not u.bar_matched or u.bar_ts_utc is None:
            continue
        matched += 1
        lag = (u.utterance_utc - u.bar_ts_utc).total_seconds()
        signed.append(float(lag))
        abs_lags.append(abs(float(lag)))

    unmatched = len(aligned) - matched
    match_rate = matched / len(aligned) if aligned else None
    median_abs = float(np.median(abs_lags)) if abs_lags else None
    p95_abs = float(np.percentile(abs_lags, 95)) if abs_lags else None

    # Histogram buckets (seconds)
    edges = [-90, -60, -30, -15, 0, 15, 30, 60, 90]
    hist: dict[str, int] = {f"{edges[i]}:{edges[i+1]}": 0 for i in range(len(edges) - 1)}
    hist["lt_-90"] = 0
    hist["gte_90"] = 0
    for lag in signed:
        if lag < edges[0]:
            hist["lt_-90"] += 1
        elif lag >= edges[-1]:
            hist["gte_90"] += 1
        else:
            for i in range(len(edges) - 1):
                if edges[i] <= lag < edges[i + 1]:
                    hist[f"{edges[i]}:{edges[i+1]}"] += 1
                    break

    sync_suspect = bool(
        match_rate is None
        or match_rate < MATCH_RATE_SUSPECT
        or (p95_abs is not None and p95_abs > P95_ABS_LAG_SUSPECT_SEC)
    )

    return {
        "match_rate": match_rate,
        "matched_count": matched,
        "unmatched_count": unmatched,
        "median_abs_lag_sec": median_abs,
        "p95_abs_lag_sec": p95_abs,
        "signed_lag_sec_sample": signed[:20],
        "lag_histogram": hist,
        "no_bar_within_60s": unmatched,
        "sync_suspect": sync_suspect,
    }


def anchor_sanity(
    transcript: TimedTranscript,
    anchors: EventAnchors,
    bars: pd.DataFrame,
) -> dict[str, Any]:
    first_start = transcript.first_start_sec
    last_end = transcript.last_end_sec
    notes: list[str] = []
    ok_first = first_start is not None and float(first_start) < 5.0
    if not ok_first:
        notes.append("first paragraph start_sec not near 0")

    # Soft volume/price jump checks near report/call
    jump_flags: dict[str, Any] = {}
    if not bars.empty and "close" in bars.columns:
        ts = pd.to_datetime(bars["ts_utc"], utc=True)
        closes = pd.to_numeric(bars["close"], errors="coerce")
        vols = (
            pd.to_numeric(bars["volume"], errors="coerce")
            if "volume" in bars.columns
            else None
        )
        for label, when in (("report_at", anchors.report_at), ("call_at", anchors.call_at)):
            if when is None:
                continue
            t = _to_utc_ts(when)
            if t is None:
                continue
            window = (ts >= t - pd.Timedelta(minutes=3)) & (ts <= t + pd.Timedelta(minutes=3))
            sub_c = closes[window]
            jump = None
            if len(sub_c) >= 2:
                jump = float(sub_c.max() / sub_c.min() - 1.0) if sub_c.min() else None
            vol_peak = None
            if vols is not None:
                sub_v = vols[window]
                if len(sub_v):
                    vol_peak = float(sub_v.max()) if pd.notna(sub_v.max()) else None
            jump_flags[label] = {"price_range_pct": jump, "volume_peak": vol_peak}

    return {
        "first_start_sec": first_start,
        "last_end_sec": last_end,
        "first_start_near_zero": ok_first,
        "anchor_jump_checks": jump_flags,
        "notes": notes,
    }


def _jaccard(a: set[int], b: set[int]) -> float | None:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def lag_sensitivity_sweep(
    *,
    aligned_base: list[AlignedUtterance],
    bars: pd.DataFrame,
    score_and_select: Callable[[list[tuple[int, datetime]]], set[int]],
    lags: tuple[int, ...] = LAG_SWEEP_SECONDS,
) -> dict[str, Any]:
    """
    score_and_select: given list of (index, utterance_utc_shifted) return selected highlight indices.
    Uses base aligned indices/start times; shifts wall clock by lag seconds.
    """
    base_pairs = [(u.index, u.utterance_utc) for u in aligned_base]
    base_selected: set[int] | None = None
    per_lag: dict[str, Any] = {}

    for lag in lags:
        pairs = [
            (idx, dt + timedelta(seconds=lag))
            for idx, dt in base_pairs
        ]
        selected = score_and_select(pairs)
        if lag == 0:
            base_selected = set(selected)
        overlap = _jaccard(base_selected or set(), set(selected)) if base_selected is not None else None
        per_lag[str(lag)] = {
            "selected_indices": sorted(selected),
            "jaccard_vs_0": overlap if lag != 0 else 1.0,
            "n_selected": len(selected),
        }

    j30 = []
    for lag in (-30, 30):
        entry = per_lag.get(str(lag)) or {}
        if entry.get("jaccard_vs_0") is not None:
            j30.append(float(entry["jaccard_vs_0"]))
    min_j30 = min(j30) if j30 else None
    timing_fragile = bool(min_j30 is not None and min_j30 < FRAGILE_JACCARD_30S)

    return {
        "lags_sec": list(lags),
        "per_lag": per_lag,
        "min_jaccard_pm30": min_j30,
        "timing_fragile": timing_fragile,
    }


def sync_badge(
    *,
    sync_suspect: bool,
    timing_fragile: bool,
) -> str:
    if sync_suspect:
        return "suspect"
    if timing_fragile:
        return "fragile"
    return "trusted"


def highlights_exploratory(
    *,
    sync_suspect: bool,
    min_jaccard_pm30: float | None,
    threshold: float = FRAGILE_JACCARD_30S,
) -> bool:
    """
    Trusted C1 gate: exploratory unless sync_suspect is false AND
    lag-sweep Jaccard overlap at ±30s is ≥ threshold (default 0.5).
    """
    if sync_suspect:
        return True
    if min_jaccard_pm30 is None:
        return True
    return float(min_jaccard_pm30) < float(threshold)


def build_sync_diagnostics(
    *,
    aligned: list[AlignedUtterance],
    anchors: EventAnchors,
    transcript: TimedTranscript,
    bars: pd.DataFrame,
    lag_sweep: dict[str, Any] | None,
    timing_lag_sec: float = 0.0,
    call_end: datetime | None = None,
) -> dict[str, Any]:
    health = join_health(aligned)
    sanity = anchor_sanity(transcript, anchors, bars)
    sweep = lag_sweep or {}
    fragile = bool(sweep.get("timing_fragile"))
    suspect = bool(health["sync_suspect"])
    badge = sync_badge(sync_suspect=suspect, timing_fragile=fragile)
    min_j30 = sweep.get("min_jaccard_pm30")
    exploratory = highlights_exploratory(
        sync_suspect=suspect,
        min_jaccard_pm30=float(min_j30) if min_j30 is not None else None,
    )
    if call_end is None and transcript.last_end_sec is not None:
        call_end = utterance_wall_clock(anchors.call_at, transcript.last_end_sec)
    return {
        "sync_contract": sync_contract(
            anchors, call_end=call_end, timing_lag_sec=timing_lag_sec
        ),
        "join_health": health,
        "anchor_sanity": sanity,
        "lag_sweep": sweep,
        "sync_badge": badge,
        "sync_trusted": badge == "trusted",
        "highlights_exploratory": exploratory,
    }
