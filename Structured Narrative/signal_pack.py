"""Load frozen production signal packs for Rank IC primaries and book ranks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore[assignment]

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
DEFAULT_PACK_PATH = REPO_ROOT / "config" / "signal_packs" / "production_v1.yaml"

# Identical to the historical hardcoded PRIMARY_HYPOTHESES tuple.
FALLBACK_HYPOTHESES: tuple[dict[str, str], ...] = (
    {
        "signal": "quant_z_pit",
        "dimension": "demand",
        "hypothesis": (
            "Demand quantitative z-score (quant_z_pit) predicts forward specific return"
        ),
    },
    {
        "signal": "agrees_with_quant",
        "dimension": "demand",
        "hypothesis": (
            "Demand narrative/quantitative agreement predicts forward specific return"
        ),
    },
    {
        "signal": "agrees_with_quant",
        "dimension": "margins",
        "hypothesis": (
            "Margins narrative/quantitative agreement predicts forward specific return"
        ),
    },
    {
        "signal": "agrees_with_quant",
        "dimension": "guidance",
        "hypothesis": (
            "Guidance narrative/quantitative agreement predicts forward specific return"
        ),
    },
)


@dataclass(frozen=True)
class SignalPack:
    pack_id: str
    hypotheses: tuple[dict[str, str], ...]
    rank_method: str = "cross_section_z"
    period_bucket: str = "period_end_calendar_quarter"
    min_names: int = 3
    primary_label_family: str = "asof"
    primary_horizon_key: str = "0_56"
    path: Path | None = None

    def iter_hypotheses(self) -> Iterable[dict[str, str]]:
        return self.hypotheses


def _normalize_hypotheses(raw: Sequence[Mapping[str, Any]]) -> tuple[dict[str, str], ...]:
    out: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        signal = str(item.get("signal") or "").strip()
        dimension = str(item.get("dimension") or "").strip()
        hypothesis = str(item.get("hypothesis") or "").strip()
        if not signal or not dimension:
            raise ValueError(f"hypotheses[{index}] requires signal and dimension")
        out.append(
            {
                "signal": signal,
                "dimension": dimension,
                "hypothesis": hypothesis
                or f"{dimension} {signal} predicts forward specific return",
            }
        )
    if not out:
        raise ValueError("signal pack hypotheses must be non-empty")
    return tuple(out)


def fallback_signal_pack() -> SignalPack:
    return SignalPack(
        pack_id="production_v1",
        hypotheses=FALLBACK_HYPOTHESES,
        path=None,
    )


def load_signal_pack(path: Path | str | None = None) -> SignalPack:
    """Load a YAML signal pack; missing/unreadable → fallback primaries."""
    target = Path(path) if path is not None else DEFAULT_PACK_PATH
    if not target.is_file():
        pack = fallback_signal_pack()
        return SignalPack(
            pack_id=pack.pack_id,
            hypotheses=pack.hypotheses,
            rank_method=pack.rank_method,
            period_bucket=pack.period_bucket,
            min_names=pack.min_names,
            primary_label_family=pack.primary_label_family,
            primary_horizon_key=pack.primary_horizon_key,
            path=target,
        )
    if yaml is None:
        raise RuntimeError("PyYAML is required to load signal packs")
    payload = yaml.safe_load(target.read_text(encoding="utf-8-sig")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"signal pack root must be a mapping: {target}")
    raw_h = payload.get("hypotheses") or []
    if not isinstance(raw_h, list):
        raise ValueError("signal pack hypotheses must be a list")
    return SignalPack(
        pack_id=str(payload.get("pack_id") or "production_v1").strip(),
        hypotheses=_normalize_hypotheses(raw_h),
        rank_method=str(payload.get("rank_method") or "cross_section_z").strip(),
        period_bucket=str(
            payload.get("period_bucket") or "period_end_calendar_quarter"
        ).strip(),
        min_names=int(payload.get("min_names") or 3),
        primary_label_family=str(payload.get("primary_label_family") or "asof").strip(),
        primary_horizon_key=str(payload.get("primary_horizon_key") or "0_56").strip(),
        path=target,
    )


def primary_hypotheses_tuple(path: Path | str | None = None) -> tuple[dict[str, str], ...]:
    return load_signal_pack(path).hypotheses
