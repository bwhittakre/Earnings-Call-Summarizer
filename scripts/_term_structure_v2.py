"""Term structure v2: jackknife combined-window premium and early dilution.

Pre-registered in .memory/entries/expe-term-structure-v2.md.
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
EARLY = (
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
)
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
    return _round(stats.get("rank_ic_mean"))


def _means(html, spearman, index, tickers, *, dimension, signal, periods, horizons):
    return {
        h: _score(
            html,
            spearman,
            index,
            tickers,
            dimension=dimension,
            signal=signal,
            periods=periods,
            horizon=h,
        )
        for h in horizons
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

    late_folds = []
    for held in software:
        sub = [t for t in software if t != held]
        m = _means(
            html,
            spearman,
            index,
            sub,
            dimension="competitive_position",
            signal="narrative_novelty",
            periods=list(LATE),
            horizons=("0_14", "14_35", "35_56", "0_56"),
        )
        c056, c014, cmid, c356 = m["0_56"], m["0_14"], m["14_35"], m["35_56"]
        ok = (
            c056 is not None
            and c014 is not None
            and cmid is not None
            and c356 is not None
            and float(c056) > float(c014)
            and float(c056) > float(cmid)
            and float(c056) > float(c356)
        )
        late_folds.append({"held_out": held, **m, "premium": ok})

    early_folds = []
    for held in software:
        sub = [t for t in software if t != held]
        m = _means(
            html,
            spearman,
            index,
            sub,
            dimension="competitive_position",
            signal="narrative_novelty",
            periods=list(EARLY),
            horizons=("0_14", "0_56"),
        )
        ok = (
            m["0_14"] is not None
            and m["0_56"] is not None
            and float(m["0_14"]) > float(m["0_56"])
        )
        early_folds.append({"held_out": held, **m, "dilutes": ok})

    des_folds = []
    for held in designers:
        sub = [t for t in designers if t != held]
        value = _score(
            html,
            spearman,
            index,
            sub,
            dimension="management_confidence",
            signal="llm_level",
            periods=list(LATE),
            horizon="0_90",
        )
        des_folds.append(
            {
                "held_out": held,
                "0_90": value,
                "positive": value is not None and float(value) > 0,
            }
        )

    checks = {
        "L1_all_premium": bool(late_folds) and all(f["premium"] for f in late_folds),
        "L2_all_dilute": bool(early_folds) and all(f["dilutes"] for f in early_folds),
        "L3_all_positive": bool(des_folds) and all(f["positive"] for f in des_folds),
    }
    payload = {
        "case_study_id": "term_structure_v2",
        "generated_at": meta.get("generated_at"),
        "checks": checks,
        "line1": checks["L1_all_premium"],
        "line2": checks["L2_all_dilute"],
        "line3": checks["L3_all_positive"],
        "case_study_pass": all(checks.values()),
        "late_premium_folds": late_folds,
        "early_dilution_folds": early_folds,
        "designer_090_folds": des_folds,
    }
    out = history / "cross_company" / "json" / "term_structure_v2_20260818.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "case_study_id": "term_structure_v2",
                "generated_at": meta.get("generated_at"),
                "checks": checks,
                "case_study_pass": payload["case_study_pass"],
                "late_fail": [f["held_out"] for f in late_folds if not f["premium"]],
                "early_fail": [f["held_out"] for f in early_folds if not f["dilutes"]],
                "des_fail": [f["held_out"] for f in des_folds if not f["positive"]],
                "des_min": min(
                    (f["0_90"] for f in des_folds if f["0_90"] is not None),
                    default=None,
                ),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
