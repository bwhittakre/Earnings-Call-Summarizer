"""Time-split the two live objects. Split locked in expe-tech-lab-v4.md."""
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
ODD = ("OPAL", "SPCX", "STRW")
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


def _score(html, spearman, index, tickers, *, dimension, signal, periods):
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
    stats = html.summarize_period_rank_ics(ics)
    return {
        "rank_ic_mean": _round(stats.get("rank_ic_mean")),
        "rank_ic_ir": _round(stats.get("rank_ic_ir")),
        "hit_rate": _round(stats.get("positive_rank_ic_hit_rate")),
        "n_periods": stats.get("n_periods"),
    }


def _resolve(universe: str, book: list[str]) -> list[str]:
    have = {t.upper() for t in book}
    if universe == "all_minus_odd":
        return [t for t in book if t not in ODD]
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
        "n_periods": len(periods),
        "candidate": cand,
        "baseline": base,
        "positive": c is not None and float(c) > 0,
        "beats": c is not None and b is not None and float(c) > float(b),
        "delta": None if c is None or b is None else _round(float(c) - float(b)),
    }


def _level_only(html, spearman, index, tickers, *, dimension, signal, periods):
    stats = _score(
        html, spearman, index, tickers, dimension=dimension, signal=signal, periods=periods
    )
    mean = stats["rank_ic_mean"]
    return {
        "n_tickers": len(tickers),
        "n_periods": len(periods),
        **stats,
        "positive": mean is not None and float(mean) > 0,
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
    core = _resolve("all_minus_odd", book)
    software = _resolve("software_cloud", book)
    semis = _resolve("semis_cycle", book)

    halves = {"early": list(EARLY), "late": list(LATE)}
    detail: dict[str, object] = {}
    checks: dict[str, bool] = {}
    for name, periods in halves.items():
        change = _pair(
            html,
            spearman,
            index,
            core,
            dimension="competitive_position",
            candidate="change_magnitude",
            baseline="llm_level",
            periods=periods,
        )
        novelty = _pair(
            html,
            spearman,
            index,
            software,
            dimension="competitive_position",
            candidate="narrative_novelty",
            baseline="llm_level",
            periods=periods,
        )
        confidence = _pair(
            html,
            spearman,
            index,
            core,
            dimension="management_confidence",
            candidate="llm_level",
            baseline="change_magnitude",
            periods=periods,
        )
        semis_conf = _level_only(
            html,
            spearman,
            index,
            semis,
            dimension="management_confidence",
            signal="llm_level",
            periods=periods,
        )
        sw_conf = _level_only(
            html,
            spearman,
            index,
            software,
            dimension="management_confidence",
            signal="llm_level",
            periods=periods,
        )
        detail[name] = {
            "change": change,
            "novelty": novelty,
            "confidence": confidence,
            "semis_confidence": semis_conf,
            "software_confidence_control": sw_conf,
        }
        checks[f"A_{name}_change_positive"] = bool(change["positive"])
        checks[f"A_{name}_change_beats_level"] = bool(change["beats"])
        checks[f"A_{name}_novelty_positive"] = bool(novelty["positive"])
        checks[f"A_{name}_novelty_beats_level"] = bool(novelty["beats"])
        checks[f"B_{name}_level_positive"] = bool(confidence["positive"])
        checks[f"B_{name}_level_beats_change"] = bool(confidence["beats"])
        checks[f"B_{name}_semis_positive"] = bool(semis_conf["positive"])

    object_a = all(v for k, v in checks.items() if k.startswith("A_"))
    object_b = all(v for k, v in checks.items() if k.startswith("B_"))
    payload = {
        "case_study_id": "tech_lab_v4",
        "generated_at": meta.get("generated_at"),
        "label": LABEL,
        "horizon": HORIZON,
        "early": list(EARLY),
        "late": list(LATE),
        "n_core": len(core),
        "checks": checks,
        "object_a": object_a,
        "object_b": object_b,
        "case_study_pass": object_a and object_b,
        "halves": detail,
    }
    out = history / "cross_company" / "json" / "tech_lab_time_split_v4_20260818.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary = {
        k: payload[k]
        for k in (
            "case_study_id",
            "generated_at",
            "n_core",
            "checks",
            "object_a",
            "object_b",
            "case_study_pass",
        )
    }
    summary["halves"] = {
        name: {
            key: {
                "candidate": row["candidate"]["rank_ic_mean"]
                if "candidate" in row
                else row.get("rank_ic_mean"),
                "baseline": row.get("baseline", {}).get("rank_ic_mean")
                if isinstance(row.get("baseline"), dict)
                else None,
                "positive": row.get("positive"),
                "beats": row.get("beats"),
            }
            for key, row in half.items()
        }
        for name, half in detail.items()
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
