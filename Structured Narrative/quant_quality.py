"""Consensus usability gates and quant quality flags for investment-grade z-scores."""
from __future__ import annotations

import json
import math
from typing import Any, Iterable, Mapping, Sequence

# Relative floor: |consensus| must be at least this fraction of |actual| (or |consensus|).
RELATIVE_CONSENSUS_FLOOR = 0.05

# Absolute |consensus| floors by LSEG measure code.
MEASURE_ABS_FLOORS: dict[int, float] = {
    27: 1.0,  # Gross Margin (percentage points)
}
DEFAULT_ABS_FLOOR = 1e-6

FLAG_NEAR_ZERO_CONSENSUS = "near_zero_consensus"
FLAG_MEMBER_SUPPRESSED = "member_suppressed"
FLAG_SPARSE_DIMENSION = "sparse_dimension"

ALL_FLAGS = (
    FLAG_NEAR_ZERO_CONSENSUS,
    FLAG_MEMBER_SUPPRESSED,
    FLAG_SPARSE_DIMENSION,
)


def _finite(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def measure_abs_floor(measure: Any) -> float:
    try:
        code = int(measure)
    except (TypeError, ValueError):
        return DEFAULT_ABS_FLOOR
    return MEASURE_ABS_FLOORS.get(code, DEFAULT_ABS_FLOOR)


def consensus_usable(
    pre_mean: Any,
    actual: Any = None,
    measure: Any = None,
    *,
    relative_floor: float = RELATIVE_CONSENSUS_FLOOR,
) -> bool:
    """Return True when percent surprise/revision may use |pre_mean| as denominator."""
    consensus = _finite(pre_mean)
    if consensus is None or consensus == 0.0:
        return False
    actual_val = _finite(actual)
    scale_base = abs(actual_val) if actual_val is not None else abs(consensus)
    threshold = max(measure_abs_floor(measure), relative_floor * scale_base)
    return abs(consensus) >= threshold


def pct_fields_for_consensus(
    *,
    surprise: float | None,
    revision: float | None,
    pre_mean: Any,
    actual: Any,
    measure: Any,
) -> dict[str, Any]:
    """Build percent fields and measure-level usability flags."""
    usable = consensus_usable(pre_mean, actual, measure)
    surprise_pct = (surprise / abs(float(pre_mean))) if usable and surprise is not None else None
    revision_pct = (revision / abs(float(pre_mean))) if usable and revision is not None else None
    # near_zero only when we had a non-null consensus that failed the gate
    consensus = _finite(pre_mean)
    near_zero = consensus is not None and not usable
    return {
        "earnings_surprise_pct": surprise_pct,
        "fwd_estimate_revision_pct": revision_pct,
        "pct_surprise_usable": usable,
        "near_zero_consensus": near_zero,
    }


def normalize_flags(flags: Iterable[str] | None) -> list[str]:
    cleaned = sorted({str(flag) for flag in (flags or ()) if flag})
    return cleaned


def flags_to_storage(flags: Iterable[str] | None) -> str:
    return json.dumps(normalize_flags(flags), separators=(",", ":"))


def flags_from_storage(value: Any) -> list[str]:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return []
    if isinstance(value, list):
        return normalize_flags(value)
    text = str(value).strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = [part.strip() for part in text.split("|") if part.strip()]
        return normalize_flags(parsed if isinstance(parsed, list) else [text])
    return normalize_flags(part.strip() for part in text.split("|"))


def quality_ok(flags: Iterable[str] | None) -> bool:
    return not normalize_flags(flags)


def dimension_quality_flags(
    *,
    member_zs_clean: Sequence[float | None] | Mapping[Any, float | None],
    member_near_zero: Sequence[bool] | Mapping[Any, bool] | None = None,
    min_members: int = 2,
) -> list[str]:
    """Build dimension-level flags from clean member zs and per-member gate marks."""
    if isinstance(member_zs_clean, Mapping):
        zs = list(member_zs_clean.values())
        keys = list(member_zs_clean.keys())
    else:
        zs = list(member_zs_clean)
        keys = list(range(len(zs)))

    flags: list[str] = []
    n_used = sum(z is not None and not (isinstance(z, float) and math.isnan(z)) for z in zs)
    if n_used < min_members:
        flags.append(FLAG_SPARSE_DIMENSION)

    if member_near_zero is not None:
        if isinstance(member_near_zero, Mapping):
            suppressed = any(bool(member_near_zero.get(key)) for key in keys)
        else:
            suppressed = any(bool(flag) for flag in member_near_zero)
        if suppressed:
            flags.append(FLAG_MEMBER_SUPPRESSED)
            if FLAG_NEAR_ZERO_CONSENSUS not in flags:
                flags.append(FLAG_NEAR_ZERO_CONSENSUS)

    return normalize_flags(flags)
