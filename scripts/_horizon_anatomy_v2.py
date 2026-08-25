"""Horizon anatomy v2: jackknife the two late-bucket objects.

Pre-registered in .memory/entries/expe-horizon-anatomy-v2.md.
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
HORIZON = "35_56"
MID = "14_35"
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
ALL = (
    "2016-Q2",
    "2016-Q3",
    "2016-Q4",
    "2017-Q1",
    "2017-Q2",
    "2017-Q3",
    "2017-Q4",
    "2018-Q1",
    "2018-Q2",
    "2018-Q3",
    "2018-Q4",
    "2019-Q1",
    "2019-Q2",
    "2019-Q3",
    "2019-Q4",
    "2020-Q1",
    "2020-Q2",
    "2020-Q3",
    "2020-Q4",
    "2021-Q1",
    *LATE,
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


IndexKey = tuple[str, str, str, str]


def _index_rows(rows, *, label: str) -> dict[IndexKey, dict[str, tuple[float, float]]]:
    out: dict[IndexKey, dict[str, tuple[float, float]]] = {}
    for row in rows:
        if str(row.get("label_key") or row.get("label") or "") != label:
            continue
        sx = _finite(row.get("signal_mean"))
        sy = _finite(row.get("label_mean"))
        if sx is None or sy is None:
            continue
        dimension = str(row.get("dimension") or "")
        signal = str(row.get("signal") or "")
        period = str(row.get("period") or "")
        horizon = str(row.get("horizon") or "")
        ticker = str(row.get("ticker") or "").upper()
        if not dimension or not signal or not period or not horizon or not ticker:
            continue
        out.setdefault((dimension, signal, period, horizon), {})[ticker] = (sx, sy)
    return out


def _score(html, spearman, index, tickers, *, dimension, signal, periods, horizon):
    want = {str(t).upper() for t in tickers}
    ics: list[float | None] = []
    for period in periods:
        pairs = index.get((dimension, signal, period, horizon)) or {}
        xs: list[float] = []
        ys: list[float] = []
        for ticker in want:
            point = pairs.get(ticker)
            if point is None:
                continue
            xs.append(point[0])
            ys.append(point[1])
        ics.append(spearman(xs, ys))
    stats = html.summarize_period_rank_ics(ics)
    return {
        "rank_ic_mean": _round(stats.get("rank_ic_mean")),
        "n_periods": stats.get("n_periods"),
    }


def _pair(html, spearman, index, tickers, *, dimension, candidate, baseline, periods, horizon):
    cand = _score(
        html,
        spearman,
        index,
        tickers,
        dimension=dimension,
        signal=candidate,
        periods=periods,
        horizon=horizon,
    )
    base = _score(
        html,
        spearman,
        index,
        tickers,
        dimension=dimension,
        signal=baseline,
        periods=periods,
        horizon=horizon,
    )
    c, b = cand["rank_ic_mean"], base["rank_ic_mean"]
    return {
        "candidate": cand,
        "baseline": base,
        "positive": c is not None and float(c) > 0,
        "beats": c is not None and b is not None and float(c) > float(b),
        "delta": None if c is None or b is None else _round(float(c) - float(b)),
    }


def _jk(html, spearman, index, tickers, *, dimension, candidate, baseline, periods, horizon):
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
            horizon=horizon,
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


def _resolve(universe: str, book: list[str]) -> list[str]:
    have = {t.upper() for t in book}
    return [t for t in load_sector_companies(universe) if t.upper() in have]


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
    index = _index_rows(rows, label=LABEL)
    software = _resolve("software_cloud", book)
    designers = _resolve("designers", book)

    nov = _pair(
        html,
        spearman,
        index,
        software,
        dimension="competitive_position",
        candidate="narrative_novelty",
        baseline="llm_level",
        periods=list(ALL),
        horizon=HORIZON,
    )
    nov_jk = _jk(
        html,
        spearman,
        index,
        software,
        dimension="competitive_position",
        candidate="narrative_novelty",
        baseline="llm_level",
        periods=list(ALL),
        horizon=HORIZON,
    )
    mid = _pair(
        html,
        spearman,
        index,
        software,
        dimension="competitive_position",
        candidate="narrative_novelty",
        baseline="llm_level",
        periods=list(ALL),
        horizon=MID,
    )
    des = _pair(
        html,
        spearman,
        index,
        designers,
        dimension="management_confidence",
        candidate="llm_level",
        baseline="change_magnitude",
        periods=list(LATE),
        horizon=HORIZON,
    )
    des_jk = _jk(
        html,
        spearman,
        index,
        designers,
        dimension="management_confidence",
        candidate="llm_level",
        baseline="change_magnitude",
        periods=list(LATE),
        horizon=HORIZON,
    )

    checks = {
        "L1_jk_all_positive": bool(nov_jk["all_positive"]),
        "L1_jk_all_beat": bool(nov_jk["all_beat"]),
        "L2_jk_all_positive": bool(des_jk["all_positive"]),
        "L2_jk_all_beat": bool(des_jk["all_beat"]),
    }
    line1 = checks["L1_jk_all_positive"] and checks["L1_jk_all_beat"]
    line2 = checks["L2_jk_all_positive"] and checks["L2_jk_all_beat"]
    payload = {
        "case_study_id": "horizon_anatomy_v2",
        "generated_at": meta.get("generated_at"),
        "checks": checks,
        "line1": line1,
        "line2": line2,
        "case_study_pass": line1 and line2,
        "software_novelty_35_56": {
            "sleeve": {
                "candidate": nov["candidate"]["rank_ic_mean"],
                "baseline": nov["baseline"]["rank_ic_mean"],
                "beats": nov["beats"],
            },
            "jackknife": nov_jk,
        },
        "software_novelty_14_35": {
            "candidate": mid["candidate"]["rank_ic_mean"],
            "baseline": mid["baseline"]["rank_ic_mean"],
            "beats": mid["beats"],
        },
        "late_designers_35_56": {
            "sleeve": {
                "candidate": des["candidate"]["rank_ic_mean"],
                "baseline": des["baseline"]["rank_ic_mean"],
                "beats": des["beats"],
            },
            "jackknife": des_jk,
        },
    }
    out = history / "cross_company" / "json" / "horizon_anatomy_v2_20260818.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "case_study_id": "horizon_anatomy_v2",
                "generated_at": meta.get("generated_at"),
                "checks": checks,
                "line1": line1,
                "line2": line2,
                "case_study_pass": line1 and line2,
                "nov_35_56": nov["candidate"]["rank_ic_mean"],
                "nov_jk_min": nov_jk["min_loo"],
                "nov_jk_worst": nov_jk["worst_held_out"],
                "des_35_56": des["candidate"]["rank_ic_mean"],
                "des_jk_min": des_jk["min_loo"],
                "des_jk_worst": des_jk["worst_held_out"],
                "mid_nov_vs_level": [
                    mid["candidate"]["rank_ic_mean"],
                    mid["baseline"]["rank_ic_mean"],
                    mid["beats"],
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
