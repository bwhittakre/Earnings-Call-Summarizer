"""C1 tape-first highlight selection with call-relative materiality floor."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Any, Iterable, Literal

import numpy as np
import pandas as pd

from ticker_reaction.align import AlignedUtterance
from ticker_reaction.reactions import ReactionRow

DEFAULT_TOP_K = 12
PERCENTILE_FLOOR = 75.0
MIN_CLEAR_FLOOR = 5
RELAXED_TOP_K = 8

Horizon = Literal["1m", "3m", "5m"]
HORIZONS: tuple[Horizon, ...] = ("1m", "3m", "5m")
HORIZON_MINUTES: dict[Horizon, int] = {"1m": 1, "3m": 3, "5m": 5}


def min_gap_sec_for_horizon(horizon: Horizon) -> float:
    """Half the view horizon, in seconds (1m→30s, 3m→90s, 5m→150s)."""
    return float(HORIZON_MINUTES[horizon]) * 30.0


def _ret_for_horizon(row: ReactionRow, horizon: Horizon) -> float | None:
    if horizon == "1m":
        return row.ret_1m
    if horizon == "3m":
        return row.ret_3m
    if horizon == "5m":
        return row.ret_5m
    raise ValueError(f"unknown horizon: {horizon}")


def _dpx_for_horizon(row: ReactionRow, horizon: Horizon) -> float | None:
    """Absolute price move (close end − close start) for the horizon."""
    if horizon == "1m":
        dpx = row.dpx_1m
    elif horizon == "3m":
        dpx = row.dpx_3m
    elif horizon == "5m":
        dpx = row.dpx_5m
    else:
        raise ValueError(f"unknown horizon: {horizon}")
    if dpx is not None and np.isfinite(dpx):
        return float(dpx)
    # Reconstruct from % return × defining-bar close when dpx was not stored.
    ret = _ret_for_horizon(row, horizon)
    if (
        ret is not None
        and np.isfinite(ret)
        and row.bar_close is not None
        and np.isfinite(row.bar_close)
    ):
        return float(ret) * float(row.bar_close)
    return None


def reaction_score_horizon(
    row: ReactionRow,
    horizon: Horizon,
) -> float:
    """Score = |Δprice| for the chosen horizon (+ tiny volume tie-break).

    Uses price points, not percent, so a $10 move scores the same at $100
    or $250 (percent would inflate moves after a drawdown).
    """
    dpx = _dpx_for_horizon(row, horizon)
    if dpx is None:
        return float("-inf")
    base = abs(float(dpx))
    vol = row.volume_1m
    if vol is not None and np.isfinite(vol) and vol > 0:
        base += 1e-12 * float(vol)
    return base


def reaction_score(
    ret_1m: float | None,
    ret_5m: float | None,
    volume_1m: float | None = None,
    *,
    dpx_1m: float | None = None,
    dpx_5m: float | None = None,
) -> float:
    """Legacy combined score max(|dpx|) when available, else max(|ret|)."""
    parts = []
    for dpx in (dpx_1m, dpx_5m):
        if dpx is not None and np.isfinite(dpx):
            parts.append(abs(float(dpx)))
    if not parts:
        if ret_1m is not None and np.isfinite(ret_1m):
            parts.append(abs(float(ret_1m)))
        if ret_5m is not None and np.isfinite(ret_5m):
            parts.append(abs(float(ret_5m)))
    if not parts:
        return float("-inf")
    base = max(parts)
    if volume_1m is not None and np.isfinite(volume_1m) and volume_1m > 0:
        base += 1e-12 * float(volume_1m)
    return base


def _parse_utterance_ts(value: str | datetime | pd.Timestamp | None) -> pd.Timestamp | None:
    if value is None or value == "":
        return None
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _spot_key_for_row(
    row: ReactionRow,
    *,
    bars: pd.DataFrame | None,
    call_at: datetime | pd.Timestamp | None,
) -> pd.Timestamp | None:
    """Defining tape bar minute: last close at/before speech (same as Ret Nm)."""
    _ = call_at
    if row.bar_ts_utc:
        parsed = _parse_utterance_ts(row.bar_ts_utc)
        if parsed is not None:
            return parsed.floor("min")
    utt = _parse_utterance_ts(row.utterance_utc)
    if utt is not None and bars is not None and not bars.empty:
        from ticker_reaction.reactions import last_bar_at_or_before

        found = last_bar_at_or_before(bars, utt)
        if found is not None:
            return found[0].floor("min")
    if utt is not None:
        return utt.floor("min")
    return None


def _apply_temporal_spacing(
    ranked: list[tuple[int, float]],
    *,
    times_by_index: dict[int, pd.Timestamp | None],
    spot_by_index: dict[int, pd.Timestamp | None] | None,
    min_gap_sec: float,
    limit: int,
    unique_spot: bool,
) -> tuple[list[int], int, int]:
    """Greedy keep-by-score with utterance gaps (and optional same-bar reject).

    Returns ``(kept_indices, n_suppressed_spacing, n_suppressed_same_spot)``.
    """
    kept: list[int] = []
    kept_times: list[pd.Timestamp] = []
    kept_spots: set[pd.Timestamp] = set()
    n_gap = 0
    n_spot = 0

    for idx, _score in ranked:
        if len(kept) >= limit:
            break
        t = times_by_index.get(idx)
        if t is not None and kept_times:
            too_close = any(
                abs((t - kt).total_seconds()) < min_gap_sec for kt in kept_times
            )
            if too_close:
                n_gap += 1
                continue
        if unique_spot:
            spot = (spot_by_index or {}).get(idx)
            if spot is not None and spot in kept_spots:
                n_spot += 1
                continue
            if spot is not None:
                kept_spots.add(spot)
        kept.append(idx)
        if t is not None:
            kept_times.append(t)

    return kept, n_gap, n_spot


def select_c1_indices_for_horizon(
    rows: Iterable[ReactionRow],
    horizon: Horizon,
    *,
    top_k: int = DEFAULT_TOP_K,
    percentile_floor: float = PERCENTILE_FLOOR,
    min_clear: int = MIN_CLEAR_FLOOR,
    relaxed_k: int = RELAXED_TOP_K,
    bars: pd.DataFrame | None = None,
    call_at: datetime | pd.Timestamp | None = None,
) -> tuple[set[int], dict[str, Any]]:
    """Top-K by |Δprice_Nm| with call-relative floor + half-horizon temporal spacing."""
    row_list = list(rows)
    rows_by_index = {r.index: r for r in row_list}
    scored: list[tuple[int, float]] = []
    for r in row_list:
        s = reaction_score_horizon(r, horizon)
        if s == float("-inf"):
            continue
        scored.append((r.index, s))

    min_gap_sec = min_gap_sec_for_horizon(horizon)
    # At most one highlight per defining 1m bar (strongest |Δprice| wins).
    unique_spot = True
    rule = f"C1_topK_abs_dpx_floor_{horizon}_temporal_gap"
    empty_diag = {
        "horizon": horizon,
        "top_k": top_k,
        "percentile_floor": percentile_floor,
        "floor_value": None,
        "n_scored": 0,
        "n_selected": 0,
        "highlights_relaxed": False,
        "selected_indices": [],
        "min_gap_sec": min_gap_sec,
        "n_suppressed_spacing": 0,
        "n_suppressed_same_spot": 0,
        "rule": rule,
        "goal": f"Largest |Δprice_{horizon}| tape moves (coincident, not causation)",
        "score_unit": "price_points",
    }
    if not scored:
        return set(), empty_diag

    scores = np.array([s for _, s in scored], dtype=float)
    floor_value = float(np.percentile(scores, percentile_floor))

    ranked = sorted(scored, key=lambda x: x[1], reverse=True)
    top = ranked[:top_k]
    cleared = [(i, s) for i, s in top if s >= floor_value]
    relaxed = False
    if len(cleared) < min_clear:
        cleared = ranked[:relaxed_k]
        relaxed = True

    times_by_index = {
        i: _parse_utterance_ts(rows_by_index[i].utterance_utc)
        for i, _ in cleared
        if i in rows_by_index
    }
    spot_by_index: dict[int, pd.Timestamp | None] | None = None
    if unique_spot:
        spot_by_index = {
            i: _spot_key_for_row(
                rows_by_index[i], bars=bars, call_at=call_at
            )
            for i, _ in cleared
            if i in rows_by_index
        }

    kept, n_gap, n_spot = _apply_temporal_spacing(
        cleared,
        times_by_index=times_by_index,
        spot_by_index=spot_by_index,
        min_gap_sec=min_gap_sec,
        limit=top_k,
        unique_spot=unique_spot,
    )

    # If floor path under-filled after spacing, retry on relaxed ranked list.
    if len(kept) < min_clear and not relaxed:
        relaxed = True
        times_by_index = {
            i: _parse_utterance_ts(rows_by_index[i].utterance_utc)
            for i, _ in ranked
            if i in rows_by_index
        }
        if unique_spot:
            spot_by_index = {
                i: _spot_key_for_row(
                    rows_by_index[i], bars=bars, call_at=call_at
                )
                for i, _ in ranked
                if i in rows_by_index
            }
        kept, n_gap, n_spot = _apply_temporal_spacing(
            ranked,
            times_by_index=times_by_index,
            spot_by_index=spot_by_index,
            min_gap_sec=min_gap_sec,
            limit=top_k,
            unique_spot=unique_spot,
        )

    selected = set(kept)
    return selected, {
        "horizon": horizon,
        "top_k": top_k,
        "percentile_floor": percentile_floor,
        "floor_value": floor_value,
        "n_scored": len(scored),
        "n_selected": len(selected),
        "highlights_relaxed": relaxed,
        "selected_indices": sorted(selected),
        "min_gap_sec": min_gap_sec,
        "n_suppressed_spacing": n_gap,
        "n_suppressed_same_spot": n_spot,
        "rule": rule,
        "goal": f"Largest |Δprice_{horizon}| tape moves (coincident, not causation)",
        "score_unit": "price_points",
    }


def select_all_horizon_highlights(
    rows: Iterable[ReactionRow],
    **kwargs: Any,
) -> dict[str, dict[str, Any]]:
    """Run C1 independently for 1m / 3m / 5m. Each value includes selected_indices."""
    row_list = list(rows)
    out: dict[str, dict[str, Any]] = {}
    for h in HORIZONS:
        selected, diag = select_c1_indices_for_horizon(row_list, h, **kwargs)
        out[h] = {**diag, "selected_indices": sorted(selected)}
    return out


def select_c1_indices(
    rows: Iterable[ReactionRow],
    *,
    top_k: int = DEFAULT_TOP_K,
    percentile_floor: float = PERCENTILE_FLOOR,
    min_clear: int = MIN_CLEAR_FLOOR,
    relaxed_k: int = RELAXED_TOP_K,
    bars: pd.DataFrame | None = None,
    call_at: datetime | pd.Timestamp | None = None,
) -> tuple[set[int], dict[str, Any]]:
    """Default product selection = C1 on |Δprice_1m| (primary view)."""
    return select_c1_indices_for_horizon(
        rows,
        "1m",
        top_k=top_k,
        percentile_floor=percentile_floor,
        min_clear=min_clear,
        relaxed_k=relaxed_k,
        bars=bars,
        call_at=call_at,
    )


def apply_horizon_highlights(
    aligned: list[AlignedUtterance],
    reactions: list[ReactionRow],
    by_horizon: dict[str, dict[str, Any]],
) -> tuple[list[AlignedUtterance], list[ReactionRow]]:
    """Set per-horizon flags; ``highlight`` mirrors the 1m view for compat."""
    sel_1m = set(by_horizon.get("1m", {}).get("selected_indices") or [])
    sel_3m = set(by_horizon.get("3m", {}).get("selected_indices") or [])
    sel_5m = set(by_horizon.get("5m", {}).get("selected_indices") or [])
    any_sel = sel_1m | sel_3m | sel_5m

    new_aligned = [
        replace(u, highlight=(u.index in sel_1m)) for u in aligned
    ]
    new_reactions = []
    for r in reactions:
        new_reactions.append(
            ReactionRow(
                **{
                    **r.__dict__,
                    "highlight": r.index in sel_1m,
                    "highlight_1m": r.index in sel_1m,
                    "highlight_3m": r.index in sel_3m,
                    "highlight_5m": r.index in sel_5m,
                }
            )
        )
    # Silence unused if needed — any_sel documents union for diagnostics callers
    _ = any_sel
    return new_aligned, new_reactions


def apply_highlights(
    aligned: list[AlignedUtterance],
    reactions: list[ReactionRow],
    selected: set[int],
) -> tuple[list[AlignedUtterance], list[ReactionRow]]:
    """Set highlight flags from a single selected set (treat as 1m view)."""
    return apply_horizon_highlights(
        aligned,
        reactions,
        {
            "1m": {"selected_indices": sorted(selected)},
            "3m": {"selected_indices": []},
            "5m": {"selected_indices": []},
        },
    )


def highlight_sequence_numbers(
    aligned: list[AlignedUtterance],
    *,
    selected: set[int] | None = None,
) -> dict[int, int]:
    """Map utterance index -> highlight label 1..K in chronological order."""
    ordered = sorted(aligned, key=lambda u: (u.utterance_utc, u.index))
    out: dict[int, int] = {}
    n = 0
    for u in ordered:
        if selected is not None:
            if u.index not in selected:
                continue
        elif not u.highlight:
            continue
        n += 1
        out[u.index] = n
    return out


def numbers_by_horizon(
    aligned: list[AlignedUtterance],
    by_horizon: dict[str, dict[str, Any]],
) -> dict[str, dict[int, int]]:
    return {
        h: highlight_sequence_numbers(
            aligned,
            selected=set(by_horizon.get(h, {}).get("selected_indices") or []),
        )
        for h in HORIZONS
    }
