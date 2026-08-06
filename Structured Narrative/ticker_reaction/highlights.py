"""C1 tape-first highlight selection with call-relative materiality floor."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterable, Literal

import numpy as np

from ticker_reaction.align import AlignedUtterance
from ticker_reaction.reactions import ReactionRow

DEFAULT_TOP_K = 12
PERCENTILE_FLOOR = 75.0
MIN_CLEAR_FLOOR = 5
RELAXED_TOP_K = 8

Horizon = Literal["1m", "3m", "5m"]
HORIZONS: tuple[Horizon, ...] = ("1m", "3m", "5m")
HORIZON_MINUTES: dict[Horizon, int] = {"1m": 1, "3m": 3, "5m": 5}


def _ret_for_horizon(row: ReactionRow, horizon: Horizon) -> float | None:
    if horizon == "1m":
        return row.ret_1m
    if horizon == "3m":
        return row.ret_3m
    if horizon == "5m":
        return row.ret_5m
    raise ValueError(f"unknown horizon: {horizon}")


def reaction_score_horizon(
    row: ReactionRow,
    horizon: Horizon,
) -> float:
    """Score = |ret_Nm| for the chosen horizon (+ tiny volume tie-break)."""
    ret = _ret_for_horizon(row, horizon)
    if ret is None or not np.isfinite(ret):
        return float("-inf")
    base = abs(float(ret))
    vol = row.volume_1m
    if vol is not None and np.isfinite(vol) and vol > 0:
        base += 1e-12 * float(vol)
    return base


def reaction_score(
    ret_1m: float | None,
    ret_5m: float | None,
    volume_1m: float | None = None,
) -> float:
    """Legacy combined score max(|ret_1m|, |ret_5m|) — kept for migration/tests."""
    parts = []
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


def select_c1_indices_for_horizon(
    rows: Iterable[ReactionRow],
    horizon: Horizon,
    *,
    top_k: int = DEFAULT_TOP_K,
    percentile_floor: float = PERCENTILE_FLOOR,
    min_clear: int = MIN_CLEAR_FLOOR,
    relaxed_k: int = RELAXED_TOP_K,
) -> tuple[set[int], dict[str, Any]]:
    """Top-K by |ret_Nm| with call-relative percentile floor on that horizon."""
    scored: list[tuple[int, float]] = []
    for r in rows:
        s = reaction_score_horizon(r, horizon)
        if s == float("-inf"):
            continue
        scored.append((r.index, s))

    rule = f"C1_topK_call_relative_floor_{horizon}"
    if not scored:
        return set(), {
            "horizon": horizon,
            "top_k": top_k,
            "percentile_floor": percentile_floor,
            "floor_value": None,
            "n_scored": 0,
            "n_selected": 0,
            "highlights_relaxed": False,
            "selected_indices": [],
            "rule": rule,
            "goal": f"Largest |ret_{horizon}| tape moves (coincident, not causation)",
        }

    scores = np.array([s for _, s in scored], dtype=float)
    floor_value = float(np.percentile(scores, percentile_floor))

    ranked = sorted(scored, key=lambda x: x[1], reverse=True)
    top = ranked[:top_k]
    cleared = [(i, s) for i, s in top if s >= floor_value]
    relaxed = False
    if len(cleared) < min_clear:
        cleared = ranked[:relaxed_k]
        relaxed = True

    selected = {i for i, _ in cleared}
    return selected, {
        "horizon": horizon,
        "top_k": top_k,
        "percentile_floor": percentile_floor,
        "floor_value": floor_value,
        "n_scored": len(scored),
        "n_selected": len(selected),
        "highlights_relaxed": relaxed,
        "selected_indices": sorted(selected),
        "rule": rule,
        "goal": f"Largest |ret_{horizon}| tape moves (coincident, not causation)",
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
) -> tuple[set[int], dict[str, Any]]:
    """Default product selection = C1 on |ret_1m| (primary view)."""
    return select_c1_indices_for_horizon(
        rows,
        "1m",
        top_k=top_k,
        percentile_floor=percentile_floor,
        min_clear=min_clear,
        relaxed_k=relaxed_k,
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
