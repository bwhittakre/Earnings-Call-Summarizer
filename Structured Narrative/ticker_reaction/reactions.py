"""Minute returns and per-utterance reaction windows."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

from ticker_reaction.align import AlignedUtterance, utterance_wall_clock
from ticker_reaction.load_transcript import EventAnchors, TimedTranscript
from ticker_reaction.sectioning import detect_qa_start_sec, section_for_start, section_meta
from ticker_reaction.speech_turns import attach_turn_context, build_speech_turns


@dataclass
class ReactionRow:
    index: int
    utterance_utc: str
    start_sec: float
    end_sec: float
    speaker: str
    speaker_role: str | None
    snippet: str
    highlight: bool
    bar_matched: bool
    bar_ts_utc: str | None
    bar_close: float | None
    ret_1m: float | None
    ret_3m: float | None
    ret_5m: float | None
    volume_1m: float | None
    dpx_1m: float | None = None  # close(t+N) - close(t); selection score uses |dpx|
    dpx_3m: float | None = None
    dpx_5m: float | None = None
    z_ret_1m: float | None = None
    ret_from_call_start: float | None = None
    ret_to_call_end: float | None = None
    section: str = "remarks"
    full_text: str = ""
    highlight_1m: bool = False
    highlight_3m: bool = False
    highlight_5m: bool = False
    speech_turn_id: int | None = None
    monologue_text: str = ""
    monologue_html: str = ""


def _ensure_utc_index(bars: pd.DataFrame) -> pd.DataFrame:
    out = bars.copy()
    out["ts_utc"] = pd.to_datetime(out["ts_utc"], utc=True)
    return out.sort_values("ts_utc").reset_index(drop=True)


def cumulative_return(
    bars: pd.DataFrame,
    start: datetime | None,
    end: datetime | None,
) -> float | None:
    """Close-to-close simple return from first bar at/after start to last bar at/before end."""
    if start is None or end is None or bars.empty:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    ts = pd.to_datetime(bars["ts_utc"], utc=True)
    mask = (ts >= pd.Timestamp(start)) & (ts <= pd.Timestamp(end))
    window = bars.loc[mask]
    if len(window) < 2:
        return None
    c0 = float(window["close"].iloc[0])
    c1 = float(window["close"].iloc[-1])
    if not np.isfinite(c0) or not np.isfinite(c1) or c0 == 0:
        return None
    return (c1 / c0) - 1.0


@dataclass(frozen=True)
class HighlightPlacement:
    """Discrete 1m tape anchor: stem sits on a real bar vertex."""

    bar_ts: pd.Timestamp  # defining bar (last at/before utterance)
    bar_close: float
    matched_pct: float | None
    match_kind: str  # defining_bar | fallback
    utterance_utc: pd.Timestamp


def _as_utc_ts(value: datetime | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def pct_points_one_decimal(ret: float | None) -> float | None:
    """Convert a simple return to percentage points rounded to one decimal."""
    if ret is None or not np.isfinite(float(ret)):
        return None
    return round(100.0 * float(ret), 1)


def call_start_close(
    bars: pd.DataFrame,
    call_at: datetime | pd.Timestamp | None,
) -> float | None:
    """Close of the first bar at/after call start (denominator for from-call %)."""
    if call_at is None or bars.empty:
        return None
    ts = pd.to_datetime(bars["ts_utc"], utc=True)
    call_ts = _as_utc_ts(call_at)
    pos = int(ts.searchsorted(call_ts, side="left"))
    if pos >= len(bars):
        return None
    close = float(bars["close"].iloc[pos])
    return close if np.isfinite(close) and close != 0 else None


def last_bar_at_or_before(
    bars: pd.DataFrame,
    t: datetime | pd.Timestamp,
) -> tuple[pd.Timestamp, float] | None:
    """Last bar at/before ``t`` — same defining bar as Ret Nm start."""
    if bars.empty:
        return None
    ts = pd.to_datetime(bars["ts_utc"], utc=True)
    target = _as_utc_ts(t)
    pos = int(ts.searchsorted(target, side="right") - 1)
    if pos < 0:
        return None
    close = float(bars["close"].iloc[pos])
    if not np.isfinite(close):
        return None
    return pd.Timestamp(ts.iloc[pos]), close


def return_from_call_at(
    bars: pd.DataFrame,
    call_at: datetime | pd.Timestamp | None,
    t: datetime | pd.Timestamp,
) -> float | None:
    """% from call-start close to the defining bar at/before ``t``."""
    c0 = call_start_close(bars, call_at)
    found = last_bar_at_or_before(bars, t)
    if c0 is None or found is None:
        return None
    _bar_ts, price = found
    return (price / c0) - 1.0


def resolve_highlight_placement(
    bars: pd.DataFrame,
    *,
    call_at: datetime | pd.Timestamp | None,
    utterance_utc: datetime | pd.Timestamp,
    ret_from_call_start: float | None,
    fallback_close: float | None = None,
) -> HighlightPlacement:
    """Anchor on the defining 1m bar (last at/before speech).

    Same bar that starts Ret Nm and defines % from call start — no
    mid-minute interpolation.
    """
    utt = _as_utc_ts(utterance_utc)
    found = last_bar_at_or_before(bars, utt)
    if found is not None:
        bar_ts, price = found
        ret = return_from_call_at(bars, call_at, utt)
        if ret is None and ret_from_call_start is not None:
            ret = ret_from_call_start
        return HighlightPlacement(
            bar_ts=bar_ts,
            bar_close=price,
            matched_pct=pct_points_one_decimal(ret),
            match_kind="defining_bar",
            utterance_utc=utt,
        )

    target_pct = pct_points_one_decimal(ret_from_call_start)
    price = fallback_close
    if price is None or not np.isfinite(float(price)):
        return HighlightPlacement(
            bar_ts=utt,
            bar_close=float("nan"),
            matched_pct=target_pct,
            match_kind="fallback",
            utterance_utc=utt,
        )
    return HighlightPlacement(
        bar_ts=utt,
        bar_close=float(price),
        matched_pct=target_pct,
        match_kind="fallback",
        utterance_utc=utt,
    )


def forward_return_anchors(
    bars: pd.DataFrame,
    t: datetime,
    minutes: int,
) -> tuple[float | None, float | None, pd.Timestamp | None, pd.Timestamp | None]:
    """Close-to-close window anchors for a forward return from utterance time.

    Returns ``(c0, c1, ts0, ts1)`` where ``c0``/``ts0`` are the last bar at/before
    ``t`` (start of the measured move) and ``c1``/``ts1`` are the last bar
    at/before ``t + minutes`` (end of the measured move).
    """
    if bars.empty:
        return None, None, None, None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    ts = pd.to_datetime(bars["ts_utc"], utc=True)
    t0 = pd.Timestamp(t)
    t1 = t0 + pd.Timedelta(minutes=minutes)

    pos0 = int(ts.searchsorted(t0, side="right") - 1)
    pos1 = int(ts.searchsorted(t1, side="right") - 1)
    if pos0 < 0 or pos1 < 0 or pos1 >= len(bars) or pos0 >= len(bars):
        return None, None, None, None
    if ts.iloc[pos0] > t0 + pd.Timedelta(minutes=1):
        return None, None, None, None
    if ts.iloc[pos1] < t0:
        return None, None, None, None

    c0 = float(bars["close"].iloc[pos0])
    c1 = float(bars["close"].iloc[pos1])
    if not np.isfinite(c0) or not np.isfinite(c1) or c0 == 0:
        return None, None, None, None
    return c0, c1, pd.Timestamp(ts.iloc[pos0]), pd.Timestamp(ts.iloc[pos1])


def _forward_return(
    bars: pd.DataFrame,
    t: datetime,
    minutes: int,
) -> tuple[float | None, float | None, float | None]:
    """Return ``(ret, volume, dpx)`` where ``dpx = c1 - c0`` (price points)."""
    c0, c1, ts0, ts1 = forward_return_anchors(bars, t, minutes)
    if c0 is None or c1 is None or ts0 is None or ts1 is None:
        return None, None, None
    ret = (c1 / c0) - 1.0
    dpx = c1 - c0

    if bars.empty:
        return ret, None, dpx
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    ts = pd.to_datetime(bars["ts_utc"], utc=True)
    t0 = pd.Timestamp(t)
    t1 = t0 + pd.Timedelta(minutes=minutes)
    pos0 = int(ts.searchsorted(t0, side="right") - 1)

    vol = None
    if "volume" in bars.columns and pos0 >= 0:
        if minutes == 1:
            nxt = pos0 + 1
            if nxt < len(bars) and ts.iloc[nxt] <= t1:
                v = bars["volume"].iloc[nxt]
                vol = float(v) if pd.notna(v) else None
        else:
            vol_mask = (ts > ts.iloc[pos0]) & (ts <= ts1)
            chunk = bars.loc[vol_mask, "volume"]
            if len(chunk):
                vol = float(pd.to_numeric(chunk, errors="coerce").fillna(0).sum())
    return ret, vol, dpx


def _snippet(text: str, limit: int = 160) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def build_reaction_rows(
    aligned: list[AlignedUtterance],
    bars: pd.DataFrame,
    *,
    anchors: EventAnchors | None = None,
    transcript: TimedTranscript | None = None,
    call_end: datetime | None = None,
) -> list[ReactionRow]:
    bars = _ensure_utc_index(bars)
    qa_start = detect_qa_start_sec(transcript) if transcript is not None else None
    turns: list = []
    index_to_turn: dict[int, int] = {}
    if transcript is not None:
        turns, index_to_turn = build_speech_turns(transcript)

    if call_end is None and anchors is not None and transcript is not None:
        if transcript.last_end_sec is not None:
            call_end = utterance_wall_clock(anchors.call_at, transcript.last_end_sec)

    rows: list[ReactionRow] = []
    for u in aligned:
        ret_1m, vol_1m, dpx_1m = _forward_return(bars, u.utterance_utc, 1)
        ret_3m, _, dpx_3m = _forward_return(bars, u.utterance_utc, 3)
        ret_5m, _, dpx_5m = _forward_return(bars, u.utterance_utc, 5)
        ret_from = None
        ret_to = None
        if anchors is not None:
            # % from call start at the defining bar (same bar as Ret Nm start).
            ret_from = return_from_call_at(bars, anchors.call_at, u.utterance_utc)
            if call_end is not None:
                ret_to = cumulative_return(bars, u.utterance_utc, call_end)
        section = section_for_start(u.start_sec, qa_start)
        para_text = " ".join((u.text or "").split())
        turn_id, mono_plain, mono_html = attach_turn_context(
            paragraph_index=u.index,
            paragraph_text=para_text,
            turns=turns,
            index_to_turn=index_to_turn,
        )
        rows.append(
            ReactionRow(
                index=u.index,
                utterance_utc=u.utterance_utc.isoformat(),
                start_sec=u.start_sec,
                end_sec=u.end_sec,
                speaker=u.speaker,
                speaker_role=u.speaker_role,
                snippet=_snippet(para_text),
                highlight=False,  # set later by C1 selector
                bar_matched=u.bar_matched,
                bar_ts_utc=u.bar_ts_utc.isoformat() if u.bar_ts_utc else None,
                bar_close=u.bar_close,
                ret_1m=ret_1m,
                ret_3m=ret_3m,
                ret_5m=ret_5m,
                volume_1m=vol_1m,
                dpx_1m=dpx_1m,
                dpx_3m=dpx_3m,
                dpx_5m=dpx_5m,
                z_ret_1m=None,
                ret_from_call_start=ret_from,
                ret_to_call_end=ret_to,
                section=section,
                full_text=para_text,
                speech_turn_id=turn_id,
                monologue_text=mono_plain,
                monologue_html=mono_html,
            )
        )

    # Call-local z-score of ret_1m
    vals = [r.ret_1m for r in rows if r.ret_1m is not None and np.isfinite(r.ret_1m)]
    if len(vals) >= 2:
        mu = float(np.mean(vals))
        sd = float(np.std(vals, ddof=1))
        if sd > 0:
            enriched = []
            for r in rows:
                z = None
                if r.ret_1m is not None and np.isfinite(r.ret_1m):
                    z = (float(r.ret_1m) - mu) / sd
                enriched.append(
                    ReactionRow(**{**r.__dict__, "z_ret_1m": z})
                )
            rows = enriched

    return rows


def scores_at_times(
    bars: pd.DataFrame,
    pairs: list[tuple[int, datetime]],
) -> list[ReactionRow]:
    """Minimal reaction rows (ret/dpx/volume) for lag-sweep scoring."""
    bars = _ensure_utc_index(bars)
    out: list[ReactionRow] = []
    for idx, t in pairs:
        ret_1m, vol_1m, dpx_1m = _forward_return(bars, t, 1)
        ret_3m, _, dpx_3m = _forward_return(bars, t, 3)
        ret_5m, _, dpx_5m = _forward_return(bars, t, 5)
        out.append(
            ReactionRow(
                index=idx,
                utterance_utc=t.isoformat(),
                start_sec=0.0,
                end_sec=0.0,
                speaker="",
                speaker_role=None,
                snippet="",
                highlight=False,
                bar_matched=True,
                bar_ts_utc=None,
                bar_close=None,
                ret_1m=ret_1m,
                ret_3m=ret_3m,
                ret_5m=ret_5m,
                volume_1m=vol_1m,
                dpx_1m=dpx_1m,
                dpx_3m=dpx_3m,
                dpx_5m=dpx_5m,
            )
        )
    return out


def summary_returns(
    bars: pd.DataFrame,
    anchors: EventAnchors,
    transcript: TimedTranscript,
) -> dict[str, Any]:
    call_end = None
    if transcript.last_end_sec is not None:
        call_end = utterance_wall_clock(anchors.call_at, transcript.last_end_sec)
    meta = section_meta(transcript, anchors)
    return {
        "cum_return_report_to_call": cumulative_return(
            bars, anchors.report_at, anchors.call_at
        ),
        "cum_return_call_to_end": cumulative_return(bars, anchors.call_at, call_end),
        "call_end_utc": call_end.isoformat() if call_end else None,
        **meta,
    }


def reactions_to_frame(rows: list[ReactionRow]) -> pd.DataFrame:
    records = []
    for r in rows:
        d = asdict(r)
        d.pop("monologue_html", None)  # report-only HTML; keep monologue_text in CSV
        records.append(d)
    return pd.DataFrame(records)


def null_return_counts(rows: list[ReactionRow]) -> dict[str, int]:
    return {
        "ret_1m_null": sum(1 for r in rows if r.ret_1m is None),
        "ret_3m_null": sum(1 for r in rows if r.ret_3m is None),
        "ret_5m_null": sum(1 for r in rows if r.ret_5m is None),
    }
