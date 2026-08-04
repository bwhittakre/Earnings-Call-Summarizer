"""Load Rank IC and consolidated-panel research artifacts for Roz tabs.

These are a separate dataset family from ``company_quarters`` history. Loaders
are lazy and return empty bundles with guidance when files are missing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

_CONSOLIDATED_STEMS = (
    "consolidated_feature_panel",
    "cross_section_panel",
)

# Inline ``components.html`` is only used below this size. Larger reports are
# served via Streamlit static file serving (see report_static.py) so the full
# consolidated_feature_panel.html (~90MB, 20 tickers) is never skipped.
_MAX_INLINE_HTML_BYTES = 15_000_000


def resolve_cross_company_root(
    history_source: str | os.PathLike[str] | None = None,
) -> Path:
    """Resolve ``…/output/cross_company`` from the history-source mount."""
    raw = history_source or os.environ.get(
        "EARNINGS_MONITOR_HISTORY_SOURCE",
        "Structured Narrative/output",
    )
    root = Path(raw)
    # Mount may already be …/output or …/output/cross_company.
    if root.name == "cross_company":
        return root
    candidate = root / "cross_company"
    if candidate.is_dir() or root.name == "output":
        return candidate
    # Repo-style: …/Structured Narrative
    nested = root / "output" / "cross_company"
    return nested


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    import pandas as pd  # type: ignore

    frame = pd.read_csv(path)
    if frame.empty:
        return []
    return frame.to_dict(orient="records")


def _mtime_iso(path: Path) -> str | None:
    if not path.is_file():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds")


def _tag_suffix(tag: str | None) -> str:
    if not tag:
        return ""
    clean = str(tag).strip().lstrip("_")
    return f"_{clean}" if clean else ""


@dataclass
class RankIcBundle:
    period_ic: list[dict[str, Any]] = field(default_factory=list)
    leaderboard: list[dict[str, Any]] = field(default_factory=list)
    agreement: list[dict[str, Any]] = field(default_factory=list)
    jackknife: list[dict[str, Any]] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.period_ic or self.leaderboard)

    @property
    def empty_message(self) -> str:
        return (
            "Rank IC artifacts not found under cross_company/. "
            "Run: python evaluate_narrative_signals.py --tickers <universe> "
            "--min-calendar-quarter 2021-Q3"
        )


@dataclass
class ConsolidatedBundle:
    spine: list[dict[str, Any]] = field(default_factory=list)
    panel: list[dict[str, Any]] = field(default_factory=list)
    stem: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return bool(self.spine or self.panel)

    @property
    def empty_message(self) -> str:
        return (
            "Consolidated panel artifacts not found under cross_company/. "
            "Run: python build_consolidated_panel_report.py --tickers <universe>"
        )


def load_rank_ic_bundle(
    *,
    history_source: str | os.PathLike[str] | None = None,
    tag: str | None = None,
) -> RankIcBundle:
    root = resolve_cross_company_root(history_source)
    suffix = _tag_suffix(tag)
    csv_dir = root / "csv"
    json_path = root / "json" / f"narrative_signal_eval{suffix}.json"

    paths = {
        "period_ic": csv_dir / f"narrative_signal_eval_period_ic{suffix}.csv",
        "leaderboard": csv_dir / f"narrative_signal_eval_leaderboard{suffix}.csv",
        "agreement": csv_dir / f"narrative_signal_eval_agreement{suffix}.csv",
        "jackknife": csv_dir / f"narrative_signal_eval_jackknife{suffix}.csv",
    }
    missing = [str(path) for path in paths.values() if not path.is_file()]
    period_ic = _read_csv_rows(paths["period_ic"])
    leaderboard = _read_csv_rows(paths["leaderboard"])
    agreement = _read_csv_rows(paths["agreement"])
    jackknife = _read_csv_rows(paths["jackknife"])

    meta: dict[str, Any] = {
        "root": str(root),
        "tag": tag,
        "period_ic_path": str(paths["period_ic"]),
        "leaderboard_path": str(paths["leaderboard"]),
        "generated_at": None,
        "tickers": [],
    }
    if json_path.is_file():
        try:
            payload = json.loads(json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            meta["generated_at"] = payload.get("generated_at") or _mtime_iso(json_path)
            tickers = payload.get("tickers") or []
            if isinstance(tickers, list):
                meta["tickers"] = [str(t).upper() for t in tickers]
            meta["json_path"] = str(json_path)
    else:
        meta["generated_at"] = _mtime_iso(paths["leaderboard"]) or _mtime_iso(
            paths["period_ic"]
        )
        missing.append(str(json_path))

    return RankIcBundle(
        period_ic=period_ic,
        leaderboard=leaderboard,
        agreement=agreement,
        jackknife=jackknife,
        meta=meta,
        missing=missing,
    )


def load_consolidated_panel(
    *,
    history_source: str | os.PathLike[str] | None = None,
    stem: str | None = None,
) -> ConsolidatedBundle:
    root = resolve_cross_company_root(history_source)
    csv_dir = root / "csv"
    spine_path = csv_dir / "cross_section_spine.csv"

    chosen_stem = stem
    panel_path: Path | None = None
    if chosen_stem:
        candidate = csv_dir / f"{chosen_stem}.csv"
        if candidate.is_file():
            panel_path = candidate
    else:
        for name in _CONSOLIDATED_STEMS:
            candidate = csv_dir / f"{name}.csv"
            if candidate.is_file():
                chosen_stem = name
                panel_path = candidate
                break

    missing: list[str] = []
    if not spine_path.is_file():
        missing.append(str(spine_path))
    if panel_path is None:
        missing.extend(str(csv_dir / f"{name}.csv") for name in _CONSOLIDATED_STEMS)

    spine = _read_csv_rows(spine_path)
    panel = _read_csv_rows(panel_path) if panel_path is not None else []
    # Prefer spine; fall back to panel rows if spine missing.
    rows = spine or panel

    meta: dict[str, Any] = {
        "root": str(root),
        "stem": chosen_stem,
        "spine_path": str(spine_path),
        "panel_path": str(panel_path) if panel_path else None,
        "generated_at": _mtime_iso(spine_path)
        or (_mtime_iso(panel_path) if panel_path else None),
        "tickers": sorted(
            {
                str(row.get("ticker", "")).upper()
                for row in rows
                if row.get("ticker")
            }
        ),
        "n_rows": len(rows),
    }
    summary_path = (
        root / "json" / f"{chosen_stem}_summary.json" if chosen_stem else None
    )
    if summary_path and summary_path.is_file():
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        if isinstance(payload, dict):
            meta["generated_at"] = (
                payload.get("generated_at") or meta["generated_at"]
            )
            if payload.get("tickers"):
                meta["tickers"] = [str(t).upper() for t in payload["tickers"]]
            meta["summary_path"] = str(summary_path)

    return ConsolidatedBundle(
        spine=spine,
        panel=panel,
        stem=chosen_stem,
        meta=meta,
        missing=missing,
    )


def filter_rank_ic_rows(
    rows: list[dict[str, Any]],
    *,
    label: str | None = None,
    horizon: str | None = None,
    dimension: str | None = None,
    signal: str | None = None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if label is not None and str(row.get("label", "")) != label:
            continue
        if horizon is not None and str(row.get("horizon", "")) != horizon:
            continue
        if dimension is not None and str(row.get("dimension", "")) != dimension:
            continue
        if signal is not None and str(row.get("signal", "")) != signal:
            continue
        out.append(row)
    return out


def unique_sorted(rows: list[dict[str, Any]], key: str) -> list[str]:
    values = sorted({str(row.get(key)) for row in rows if row.get(key) not in (None, "")})
    return values


def resolve_report_html(
    stem: str,
    *,
    history_source: str | os.PathLike[str] | None = None,
    tag: str | None = None,
    max_bytes: int | None = None,
) -> Path | None:
    """Resolve ``…/reports/{stem}{tag}.html`` when present.

    ``max_bytes`` is optional; when set, oversized files are skipped (used for
    inline-embed eligibility checks, not for choosing which report exists).
    """
    root = resolve_cross_company_root(history_source)
    suffix = _tag_suffix(tag)
    path = root / "reports" / f"{stem}{suffix}.html"
    if not path.is_file():
        return None
    if max_bytes is not None and path.stat().st_size > max_bytes:
        return None
    return path


def resolve_rank_ic_html(
    *,
    history_source: str | os.PathLike[str] | None = None,
    tag: str | None = None,
) -> Path | None:
    """Locate the Rank IC HTML report (untagged, then tagged)."""
    found = resolve_report_html(
        "narrative_signal_eval",
        history_source=history_source,
        tag=tag,
    )
    if found is not None:
        return found
    if tag:
        return None
    return resolve_report_html(
        "narrative_signal_eval",
        history_source=history_source,
        tag=None,
    )


def resolve_consolidated_html(
    *,
    history_source: str | os.PathLike[str] | None = None,
    stem: str | None = None,
) -> Path | None:
    """Locate consolidated panel HTML, preferring the full 20-ticker report."""
    stems = (stem,) if stem else _CONSOLIDATED_STEMS
    for name in stems:
        if not name:
            continue
        found = resolve_report_html(name, history_source=history_source)
        if found is not None:
            return found
    return None


def can_inline_html(path: Path | None) -> bool:
    """True when the file is small enough for ``components.html`` inlining."""
    if path is None or not path.is_file():
        return False
    return path.stat().st_size <= _MAX_INLINE_HTML_BYTES


def html_report_meta(path: Path | None) -> dict[str, Any]:
    """Lightweight provenance for an embedded HTML report."""
    if path is None or not path.is_file():
        return {"path": None, "generated_at": None, "size_bytes": None}
    return {
        "path": str(path),
        "generated_at": _mtime_iso(path),
        "size_bytes": path.stat().st_size,
        "stem": path.stem,
    }
