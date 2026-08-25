"""v9: IBM-optional late software change; designer leave-one-period.

Pre-registered in .memory/entries/expe-tech-lab-v9.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.company_lists import load_sector_companies  # noqa: E402
from services.earnings_monitor.dashboard.rank_ic_research import (  # noqa: E402
    _rank_ic_html,
    _spearman,
)
from services.earnings_monitor.dashboard.research_data import (  # noqa: E402
    load_rank_ic_bundle,
)

LABEL = "asof"
HORIZON = "0_56"
LATE = (
    "2021-Q2",
    "2021-Q3",
    "2021-Q4",
    "2022-Q1",
    "2022-Q2",
    "2022-Q3",
    "2022-Q4",
    "2023-Q1",
    "2023-Q2",
    "2023-Q3",
    "2023-Q4",
    "2024-Q1",
    "2024-Q2",
    "2024-Q3",
    "2024-Q4",
    "2025-Q1",
    "2025-Q2",
    "2025-Q3",
    "2025-Q4",
    "2026-Q1",
)


def _round(value: object) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _finite(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:
        return None
    return number


IndexKey = tuple[str, str, str]


def _index_rows(rows, *, label: str, horizon: str) -> dict[IndexKey, dict[str, tuple[float, float]]]:
    out: dict[IndexKey, dict[str, tuple[float, float]]] = {}
    for row in rows:
        if str(row.get("label_key") or row.get("label") or "") != label:
            continue
        if str(row.get("horizon") or "") != horizon:
            continue
        sx = _finite(row.get("signal_mean"))
        sy = _finite(row.get("label_mean"))
        if sx is None or sy is None:
            continue
        dimension = str(row.get("dimension") or "")
        signal = str(row.get("signal") or "")
        period = str(row.get("period") or "")
        ticker = str(row.get("ticker") or "").upper()
        if not dimension or not signal or not period or not ticker:
            continue
        out.setdefault((dimension, signal, period), {})[ticker] = (sx, sy)
    return out


def _ics(spearman, index, tickers, *, dimension, signal, periods):
    want = {str(t).upper() for t in tickers}
    ics: list[float | None] = []
    for period in periods:
        pairs = index.get((dimension, signal, period)) or {}
        xs: list[float] = []
        ys: list[float] = []
        for ticker in want:
            point = pairs.get(ticker)
            if point is None:
                continue
            xs.append(point[0])
            ys.append(point[1])
        ics.append(spearman(xs, ys))
    return ics


def _score(html, spearman, index, tickers, *, dimension, signal, periods):
    ics = _ics(spearman, index, tickers, dimension=dimension, signal=signal, periods=periods)
    stats = html.summarize_period_rank_ics(ics)
    return {
        "rank_ic_mean": _round(stats.get("rank_ic_mean")),
        "rank_ic_ir": _round(stats.get("rank_ic_ir")),
        "hit_rate": _round(stats.get("positive_rank_ic_hit_rate")),
        "n_periods": stats.get("n_periods"),
    }


def _resolve(universe: str, book: list[str]) -> list[str]:
    have = {t.upper() for t in book}
    return [t for t in load_sector_companies(universe) if t.upper() in have]


def _pair(html, spearman, index, tickers, *, dimension, candidate, baseline, periods):
    cand = _score(
        html, spearman, index, tickers, dimension=dimension, signal=candidate, periods=periods
    )
    base = _score(
        html, spearman, index, tickers, dimension=dimension, signal=baseline, periods=periods
    )
    c, b = cand["rank_ic_mean"], base["rank_ic_mean"]
    return {
        "n_tickers": len(tickers),
        "candidate": cand,
        "baseline": base,
        "positive": c is not None and float(c) > 0,
        "beats": c is not None and b is not None and float(c) > float(b),
        "delta": None if c is None or b is None else _round(float(c) - float(b)),
    }


def _jk_beats(html, spearman, index, tickers, *, dimension, candidate, baseline, periods):
    folds = []
    for held in tickers:
        sub = [t for t in tickers if t != held]
        pair = _pair(
            html,
            spearman,
            index,
            sub,
            dimension=dimension,
            candidate=candidate,
            baseline=baseline,
            periods=periods,
        )
        folds.append(
            {
                "held_out": held,
                "candidate": pair["candidate"]["rank_ic_mean"],
                "baseline": pair["baseline"]["rank_ic_mean"],
                "positive": pair["positive"],
                "beats": pair["beats"],
                "delta": pair["delta"],
            }
        )
    pos = [f["candidate"] for f in folds if f["candidate"] is not None]
    return {
        "all_positive": bool(pos) and all(f["positive"] for f in folds),
        "all_beat": bool(folds) and all(f["beats"] for f in folds),
        "min_loo": _round(min(pos)) if pos else None,
        "max_loo": _round(max(pos)) if pos else None,
        "worst_held_out": min(
            folds, key=lambda f: f["candidate"] if f["candidate"] is not None else 99
        )["held_out"]
        if folds
        else None,
        "folds": folds,
    }


def _period_drop(html, ics: list[float | None], periods: list[str]):
    folds = []
    for i, period in enumerate(periods):
        sub = [ic for j, ic in enumerate(ics) if j != i]
        stats = html.summarize_period_rank_ics(sub)
        mean = _round(stats.get("rank_ic_mean"))
        folds.append(
            {
                "held_out": period,
                "mean": mean,
                "positive": mean is not None and float(mean) > 0,
            }
        )
    pos = [f["mean"] for f in folds if f["mean"] is not None]
    return {
        "all_positive": bool(pos) and all(f["positive"] for f in folds),
        "min_mean": _round(min(pos)) if pos else None,
        "max_mean": _round(max(pos)) if pos else None,
        "worst_held_out": min(
            folds, key=lambda f: f["mean"] if f["mean"] is not None else 99
        )["held_out"]
        if folds
        else None,
        "folds": folds,
    }


def _compact(pair: dict) -> dict:
    return {
        "candidate": pair["candidate"]["rank_ic_mean"],
        "baseline": pair["baseline"]["rank_ic_mean"],
        "beats": pair["beats"],
        "delta": pair["delta"],
        "positive": pair["positive"],
    }


def main() -> None:
    history = ROOT / "Structured Narrative" / "output"
    meta = json.loads(
        (history / "cross_company" / "json" / "narrative_signal_eval.json").read_text(
            encoding="utf-8"
        )
    )
    book = [str(t).upper() for t in (meta.get("tickers") or [])]
    rows = load_rank_ic_bundle(history_source=str(history)).company_period
    html = _rank_ic_html()
    spearman = _spearman()
    index = _index_rows(rows, label=LABEL, horizon=HORIZON)
    software_pure = _resolve("software_pure", book)
    designers = _resolve("designers", book)
    late = list(LATE)

    chg = _pair(
        html,
        spearman,
        index,
        software_pure,
        dimension="competitive_position",
        candidate="change_magnitude",
        baseline="llm_level",
        periods=late,
    )
    jk = _jk_beats(
        html,
        spearman,
        index,
        software_pure,
        dimension="competitive_position",
        candidate="change_magnitude",
        baseline="llm_level",
        periods=late,
    )
    des_ics = _ics(
        spearman,
        index,
        designers,
        dimension="management_confidence",
        signal="llm_level",
        periods=late,
    )
    des_drop = _period_drop(html, des_ics, late)

    checks = {
        "L1_positive": bool(chg["positive"]),
        "L1_beats_level": bool(chg["beats"]),
        "L1_jk_all_positive": bool(jk["all_positive"]),
        "L1_jk_all_beat": bool(jk["all_beat"]),
        "L2_period_drop_all_positive": bool(des_drop["all_positive"]),
    }
    line1 = all(checks[k] for k in checks if k.startswith("L1_"))
    line2 = bool(checks["L2_period_drop_all_positive"])
    payload = {
        "case_study_id": "tech_lab_v9",
        "generated_at": meta.get("generated_at"),
        "checks": checks,
        "line1": line1,
        "line2": line2,
        "case_study_pass": line1 and line2,
        "late_software_pure_change": {
            "pair": _compact(chg),
            "jackknife": jk,
        },
        "late_designers_period_drop": des_drop,
    }
    out = history / "cross_company" / "json" / "tech_lab_v9_20260818.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "case_study_id": "tech_lab_v9",
                "generated_at": meta.get("generated_at"),
                "checks": checks,
                "line1": line1,
                "line2": line2,
                "case_study_pass": line1 and line2,
                "sleeve": _compact(chg),
                "jk_min": jk["min_loo"],
                "jk_worst": jk["worst_held_out"],
                "period_drop_min": des_drop["min_mean"],
                "period_drop_worst": des_drop["worst_held_out"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
