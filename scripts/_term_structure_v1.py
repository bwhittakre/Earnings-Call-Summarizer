"""Term structure v1: atlas + era persistence + concordance + 0_90.

Pre-registered in .memory/entries/expe-term-structure-v1.md.
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
ODD = ("OPAL", "SPCX", "STRW")
BUCKETS = ("0_14", "14_35", "35_56")
HORIZONS = ("0_14", "14_35", "35_56", "0_56", "0_90")
DIMENSIONS = (
    "demand",
    "margins",
    "earnings_power",
    "capital_allocation",
    "guidance",
    "management_confidence",
    "competitive_position",
    "macro_regulatory_risk",
)
SIGNALS = (
    "llm_level",
    "change_magnitude",
    "surprise_magnitude",
    "narrative_novelty",
    "quant_z_pit",
    "agrees_with_quant",
)
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
ALL = EARLY + LATE


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


def _period_ics(spearman, index, tickers, *, dimension, signal, periods, horizon):
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
    return ics


def _score(html, spearman, index, tickers, *, dimension, signal, periods, horizon):
    ics = _period_ics(
        spearman,
        index,
        tickers,
        dimension=dimension,
        signal=signal,
        periods=periods,
        horizon=horizon,
    )
    stats = html.summarize_period_rank_ics(ics)
    return {
        "rank_ic_mean": _round(stats.get("rank_ic_mean")),
        "rank_ic_ir": _round(stats.get("rank_ic_ir")),
        "hit_rate": _round(stats.get("positive_rank_ic_hit_rate")),
        "n_periods": stats.get("n_periods"),
        "ics": [_round(ic) for ic in ics],
    }


def _curve(html, spearman, index, tickers, *, dimension, signal, periods):
    return {
        horizon: _score(
            html,
            spearman,
            index,
            tickers,
            dimension=dimension,
            signal=signal,
            periods=periods,
            horizon=horizon,
        )
        for horizon in HORIZONS
    }


def _mean(curve: dict, horizon: str) -> float | None:
    return curve[horizon]["rank_ic_mean"]


def _mid_hump(curve: dict) -> bool:
    a, b, c = _mean(curve, "0_14"), _mean(curve, "14_35"), _mean(curve, "35_56")
    return a is not None and b is not None and c is not None and b > a and b > c


def _u_shape(curve: dict) -> bool:
    a, b, c = _mean(curve, "0_14"), _mean(curve, "14_35"), _mean(curve, "35_56")
    return a is not None and b is not None and c is not None and a > b and c > b


def _shape_name(curve: dict) -> str | None:
    a, b, c = _mean(curve, "0_14"), _mean(curve, "14_35"), _mean(curve, "35_56")
    if a is None or b is None or c is None:
        return None
    if b < a and b < c:
        return "U"
    peak = max(a, b, c)
    if peak == a:
        return "front"
    if peak == b:
        return "mid"
    return "back"


def _period_u_count(front: list, mid: list, back: list) -> dict:
    hits = 0
    scored = 0
    flags: list[bool | None] = []
    for a, b, c in zip(front, mid, back, strict=True):
        if a is None or b is None or c is None:
            flags.append(None)
            continue
        scored += 1
        ok = float(a) > float(b) and float(c) > float(b)
        hits += int(ok)
        flags.append(ok)
    return {"hits": hits, "scored": scored, "flags": flags}


def _period_mid_count(front: list, mid: list, back: list) -> dict:
    hits = 0
    scored = 0
    for a, b, c in zip(front, mid, back, strict=True):
        if a is None or b is None or c is None:
            continue
        scored += 1
        if float(b) > float(a) and float(b) > float(c):
            hits += 1
    return {"hits": hits, "scored": scored}


def _period_back_count(front: list, back: list) -> dict:
    hits = 0
    scored = 0
    for a, c in zip(front, back, strict=True):
        if a is None or c is None:
            continue
        scored += 1
        if float(c) > float(a):
            hits += 1
    return {"hits": hits, "scored": scored}


def _resolve(universe: str, book: list[str]) -> list[str]:
    have = {t.upper() for t in book}
    if universe == "core22":
        return [t for t in book if t not in ODD]
    return [t for t in load_sector_companies(universe) if t.upper() in have]


def _compact_curve(curve: dict) -> dict:
    return {h: curve[h]["rank_ic_mean"] for h in HORIZONS} | {
        "shape": _shape_name(curve),
        "ir_056": curve["0_56"]["rank_ic_ir"],
        "n_056": curve["0_56"]["n_periods"],
    }


def _atlas(html, spearman, index, universes: dict[str, list[str]], windows: dict[str, tuple]):
    rows = []
    for uni_name, tickers in universes.items():
        for window_name, periods in windows.items():
            for dimension in DIMENSIONS:
                for signal in SIGNALS:
                    curve = _curve(
                        html,
                        spearman,
                        index,
                        tickers,
                        dimension=dimension,
                        signal=signal,
                        periods=list(periods),
                    )
                    if all(_mean(curve, h) is None for h in BUCKETS):
                        continue
                    rows.append(
                        {
                            "universe": uni_name,
                            "window": window_name,
                            "dimension": dimension,
                            "signal": signal,
                            **_compact_curve(curve),
                        }
                    )
    return rows


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
    universes = {
        "core22": _resolve("core22", book),
        "software_cloud": _resolve("software_cloud", book),
        "designers": _resolve("designers", book),
    }
    windows = {"full": ALL, "early": EARLY, "late": LATE}

    demand_early = _curve(
        html, spearman, index, universes["core22"],
        dimension="demand", signal="quant_z_pit", periods=list(EARLY),
    )
    demand_late = _curve(
        html, spearman, index, universes["core22"],
        dimension="demand", signal="quant_z_pit", periods=list(LATE),
    )
    demand_full = _curve(
        html, spearman, index, universes["core22"],
        dimension="demand", signal="quant_z_pit", periods=list(ALL),
    )
    nov_early = _curve(
        html, spearman, index, universes["software_cloud"],
        dimension="competitive_position", signal="narrative_novelty", periods=list(EARLY),
    )
    nov_late = _curve(
        html, spearman, index, universes["software_cloud"],
        dimension="competitive_position", signal="narrative_novelty", periods=list(LATE),
    )
    nov_full = _curve(
        html, spearman, index, universes["software_cloud"],
        dimension="competitive_position", signal="narrative_novelty", periods=list(ALL),
    )
    lvl_090 = _score(
        html, spearman, index, universes["software_cloud"],
        dimension="competitive_position", signal="llm_level", periods=list(ALL), horizon="0_90",
    )
    des_late = _curve(
        html, spearman, index, universes["designers"],
        dimension="management_confidence", signal="llm_level", periods=list(LATE),
    )
    macro_nov = _curve(
        html, spearman, index, universes["core22"],
        dimension="macro_regulatory_risk", signal="narrative_novelty", periods=list(ALL),
    )
    macro_lvl = _curve(
        html, spearman, index, universes["core22"],
        dimension="macro_regulatory_risk", signal="llm_level", periods=list(ALL),
    )
    conf_nov = _curve(
        html, spearman, index, universes["core22"],
        dimension="management_confidence", signal="narrative_novelty", periods=list(ALL),
    )
    conf_lvl = _curve(
        html, spearman, index, universes["core22"],
        dimension="management_confidence", signal="llm_level", periods=list(ALL),
    )

    nov_u = _period_u_count(
        nov_full["0_14"]["ics"], nov_full["14_35"]["ics"], nov_full["35_56"]["ics"]
    )
    demand_mid = _period_mid_count(
        demand_full["0_14"]["ics"], demand_full["14_35"]["ics"], demand_full["35_56"]["ics"]
    )
    des_back = _period_back_count(des_late["0_14"]["ics"], des_late["35_56"]["ics"])

    nov_090 = _mean(nov_full, "0_90")
    lvl_090_mean = lvl_090["rank_ic_mean"]
    demand_090 = _mean(demand_full, "0_90")
    demand_056 = _mean(demand_full, "0_56")
    macro_ok = (
        _mean(macro_nov, "0_56") is not None
        and float(_mean(macro_nov, "0_56")) > 0
        and _mean(macro_lvl, "0_56") is not None
        and float(_mean(macro_nov, "0_56")) > float(_mean(macro_lvl, "0_56"))
    )
    conf_ok = (
        _mean(conf_nov, "0_56") is not None
        and float(_mean(conf_nov, "0_56")) > 0
        and _mean(conf_lvl, "0_56") is not None
        and float(_mean(conf_nov, "0_56")) > float(_mean(conf_lvl, "0_56"))
    )

    checks = {
        "A1_demand_early_mid": _mid_hump(demand_early),
        "A1_demand_late_mid": _mid_hump(demand_late),
        "A2_nov_early_u": _u_shape(nov_early),
        "A2_nov_late_u": _u_shape(nov_late),
        "B1_nov_u_periods": nov_u["hits"] >= 20 and nov_u["scored"] >= 20,
        "C1_nov_090_pos": nov_090 is not None and float(nov_090) > 0,
        "C1_nov_090_beats": (
            nov_090 is not None
            and lvl_090_mean is not None
            and float(nov_090) > float(lvl_090_mean)
        ),
    }
    line_a = all(checks[k] for k in checks if k.startswith("A"))
    line_b = bool(checks["B1_nov_u_periods"])
    line_c = checks["C1_nov_090_pos"] and checks["C1_nov_090_beats"]
    diagnostics = {
        "demand_mid_periods": demand_mid,
        "demand_mid_ge_20": demand_mid["hits"] >= 20 and demand_mid["scored"] >= 20,
        "designer_back_periods": des_back,
        "designer_back_ge_12": des_back["hits"] >= 12 and des_back["scored"] >= 12,
        "demand_090_lt_056": (
            demand_090 is not None
            and demand_056 is not None
            and float(demand_090) < float(demand_056)
        ),
        "macro_novelty_056_beats": macro_ok,
        "confidence_novelty_056_beats": conf_ok,
    }

    atlas = _atlas(html, spearman, index, universes, windows)
    payload = {
        "case_study_id": "term_structure_v1",
        "generated_at": meta.get("generated_at"),
        "checks": checks,
        "line_a": line_a,
        "line_b": line_b,
        "line_c": line_c,
        "case_study_pass": line_a and line_b and line_c,
        "diagnostics": diagnostics,
        "demand_quant_core22": {
            "early": _compact_curve(demand_early),
            "late": _compact_curve(demand_late),
            "full": _compact_curve(demand_full),
        },
        "software_novelty": {
            "early": _compact_curve(nov_early),
            "late": _compact_curve(nov_late),
            "full": _compact_curve(nov_full),
            "level_0_90": lvl_090_mean,
            "period_u": {"hits": nov_u["hits"], "scored": nov_u["scored"]},
        },
        "late_designers_confidence": _compact_curve(des_late),
        "macro_novelty_core22": _compact_curve(macro_nov),
        "macro_level_core22": _compact_curve(macro_lvl),
        "confidence_novelty_core22": _compact_curve(conf_nov),
        "confidence_level_core22": _compact_curve(conf_lvl),
        "atlas": atlas,
    }
    out = history / "cross_company" / "json" / "term_structure_v1_20260818.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    # Rank atlas cells on full core22 0_56 for the print summary.
    core_full = [
        r for r in atlas
        if r["universe"] == "core22" and r["window"] == "full" and r.get("0_56") is not None
    ]
    top = sorted(core_full, key=lambda r: float(r["0_56"]), reverse=True)[:8]
    print(
        json.dumps(
            {
                "case_study_id": "term_structure_v1",
                "generated_at": meta.get("generated_at"),
                "checks": checks,
                "line_a": line_a,
                "line_b": line_b,
                "line_c": line_c,
                "case_study_pass": line_a and line_b and line_c,
                "diagnostics": {
                    k: v for k, v in diagnostics.items() if not isinstance(v, dict)
                } | {
                    "demand_mid_periods": [
                        diagnostics["demand_mid_periods"]["hits"],
                        diagnostics["demand_mid_periods"]["scored"],
                    ],
                    "designer_back_periods": [
                        diagnostics["designer_back_periods"]["hits"],
                        diagnostics["designer_back_periods"]["scored"],
                    ],
                },
                "demand": payload["demand_quant_core22"],
                "novelty": payload["software_novelty"],
                "designers": payload["late_designers_confidence"],
                "macro_nov_056": _mean(macro_nov, "0_56"),
                "macro_lvl_056": _mean(macro_lvl, "0_56"),
                "conf_nov_056": _mean(conf_nov, "0_56"),
                "conf_lvl_056": _mean(conf_lvl, "0_56"),
                "atlas_n": len(atlas),
                "top_core22_full_056": [
                    [r["dimension"], r["signal"], r["0_56"], r["shape"]] for r in top
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
