"""Align timed transcript paragraphs to wall-clock UTC and nearest bars."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from ticker_reaction.load_transcript import EventAnchors, TimedTranscript


@dataclass(frozen=True)
class AlignedUtterance:
    index: int
    start_sec: float
    end_sec: float
    speaker: str
    speaker_role: str | None
    text: str
    url: str | None
    utterance_utc: datetime
    utterance_end_utc: datetime
    bar_ts_utc: datetime | None
    bar_close: float | None
    bar_matched: bool
    highlight: bool


def utterance_wall_clock(call_at: datetime, start_sec: float) -> datetime:
    if call_at.tzinfo is None:
        call_at = call_at.replace(tzinfo=timezone.utc)
    return call_at + timedelta(seconds=float(start_sec))


def align_utterances(
    transcript: TimedTranscript,
    anchors: EventAnchors,
    bars: pd.DataFrame,
    *,
    max_bar_distance: pd.Timedelta | timedelta = timedelta(minutes=1),
    timing_lag_sec: float = 0.0,
) -> list[AlignedUtterance]:
    """Map each paragraph to UTC via call_at + start (+ optional lag); nearest bar ≤ 1 minute."""
    if bars is None or bars.empty:
        bar_index = pd.DatetimeIndex([], tz="UTC")
        closes = []
    else:
        bar_index = pd.DatetimeIndex(pd.to_datetime(bars["ts_utc"], utc=True))
        closes = list(pd.to_numeric(bars["close"], errors="coerce").astype(float))

    max_delta = pd.Timedelta(max_bar_distance)
    lag = timedelta(seconds=float(timing_lag_sec))
    aligned: list[AlignedUtterance] = []

    for para in transcript.paragraphs:
        start_utc = utterance_wall_clock(anchors.call_at, para.start_sec) + lag
        end_utc = utterance_wall_clock(anchors.call_at, para.end_sec) + lag
        bar_ts = None
        bar_close = None
        matched = False
        if len(bar_index) > 0:
            # Last bar at/before utterance — same clock as ret_from_call_start.
            # Do not snap forward to a nearer *after* bar (that can be the recovery
            # print and disagree with the table's from-call-start %).
            pos = int(bar_index.searchsorted(start_utc, side="right") - 1)
            if pos < 0:
                pos = 0
            delta = abs(bar_index[pos] - pd.Timestamp(start_utc))
            if delta <= max_delta:
                matched = True
                bar_ts = bar_index[pos].to_pydatetime()
                cval = closes[pos]
                bar_close = float(cval) if cval == cval else None  # NaN check

        aligned.append(
            AlignedUtterance(
                index=para.index,
                start_sec=para.start_sec,
                end_sec=para.end_sec,
                speaker=para.speaker,
                speaker_role=para.speaker_role,
                text=para.text,
                url=para.url,
                utterance_utc=start_utc,
                utterance_end_utc=end_utc,
                bar_ts_utc=bar_ts,
                bar_close=bar_close,
                bar_matched=matched,
                highlight=False,  # set later by C1 tape-first selector
            )
        )
    return aligned


def alignment_stats(
    aligned: list[AlignedUtterance],
    bars: pd.DataFrame,
    anchors: EventAnchors,
    transcript: TimedTranscript,
) -> dict[str, Any]:
    matched = sum(1 for u in aligned if u.bar_matched)
    unmatched = len(aligned) - matched
    first_u = aligned[0].utterance_utc.isoformat() if aligned else None
    last_u = aligned[-1].utterance_utc.isoformat() if aligned else None
    bar_start = bars["ts_utc"].iloc[0].isoformat() if not bars.empty else None
    bar_end = bars["ts_utc"].iloc[-1].isoformat() if not bars.empty else None
    call_end = None
    if transcript.last_end_sec is not None:
        call_end = utterance_wall_clock(anchors.call_at, transcript.last_end_sec).isoformat()
    return {
        "paragraph_count": len(aligned),
        "matched_count": matched,
        "unmatched_count": unmatched,
        "match_rate": (matched / len(aligned)) if aligned else None,
        "first_utterance_utc": first_u,
        "last_utterance_utc": last_u,
        "call_end_utc": call_end,
        "call_at": anchors.call_at.isoformat(),
        "report_at": anchors.report_at.isoformat() if anchors.report_at else None,
        "bar_window_start_utc": bar_start,
        "bar_window_end_utc": bar_end,
    }
