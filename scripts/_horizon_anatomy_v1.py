"""Horizon anatomy v1: prints vs live objects across 0_14 / 14_35 / 35_56.

Pre-registered in .memory/entries/expe-horizon-anatomy-v1.md.
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
HORIZONS = ("0_14", "14_35", "35_56", "0_56")
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
    n_scored = 0
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
        ic = spearman(xs, ys)
        ics.append(ic)
        if ic is not None:
            n_scored += 1
    stats = html.summarize_period_rank_ics(ics)
    return {
        "rank_ic_mean": _round(stats.get("rank_ic_mean")),
        "rank_ic_ir": _round(stats.get("rank_ic_ir")),
        "hit_rate": _round(stats.get("positive_rank_ic_hit_rate")),
        "n_periods": stats.get("n_periods"),
        "n_scored": n_scored,
    }


def _across_horizons(html, spearman, index, tickers, *, dimension, signal, periods):
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


def _beats(left: dict, right: dict) -> bool:
    a, b = left.get("rank_ic_mean"), right.get("rank_ic_mean")
    return a is not None and b is not None and float(a) > float(b)


def _positive(cell: dict) -> bool:
    value = cell.get("rank_ic_mean")
    return value is not None and float(value) > 0


def _resolve(universe: str, book: list[str]) -> list[str]:
    have = {t.upper() for t in book}
    if universe == "core22":
        return [t for t in book if t not in ODD]
    return [t for t in load_sector_companies(universe) if t.upper() in have]


def _all_periods(index) -> list[str]:
    seen = {key[2] for key in index}
    return sorted(seen)


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
    core22 = _resolve("core22", book)
    software = _resolve("software_cloud", book)
    designers = _resolve("designers", book)
    # All asof periods present in the book, same calendar order as v4.
    periods = [
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
    ]
    present = set(_all_periods(index))
    periods = [p for p in periods if p in present]
    late = [p for p in LATE if p in present]

    demand_quant = _across_horizons(
        html,
        spearman,
        index,
        core22,
        dimension="demand",
        signal="quant_z_pit",
        periods=periods,
    )
    guidance_surprise = _across_horizons(
        html,
        spearman,
        index,
        core22,
        dimension="guidance",
        signal="surprise_magnitude",
        periods=periods,
    )
    software_nov = _across_horizons(
        html,
        spearman,
        index,
        software,
        dimension="competitive_position",
        signal="narrative_novelty",
        periods=periods,
    )
    software_lvl = _across_horizons(
        html,
        spearman,
        index,
        software,
        dimension="competitive_position",
        signal="llm_level",
        periods=periods,
    )
    des_conf = _across_horizons(
        html,
        spearman,
        index,
        designers,
        dimension="management_confidence",
        signal="llm_level",
        periods=late,
    )
    des_chg = _across_horizons(
        html,
        spearman,
        index,
        designers,
        dimension="management_confidence",
        signal="change_magnitude",
        periods=late,
    )
    core_chg = _across_horizons(
        html,
        spearman,
        index,
        core22,
        dimension="competitive_position",
        signal="change_magnitude",
        periods=periods,
    )

    checks = {
        "L1_demand_front": _beats(demand_quant["0_14"], demand_quant["35_56"]),
        "L1_guidance_front": _beats(guidance_surprise["0_14"], guidance_surprise["35_56"]),
        "L2_nov_014_pos": _positive(software_nov["0_14"]),
        "L2_nov_014_beats": _beats(software_nov["0_14"], software_lvl["0_14"]),
        "L2_nov_3556_pos": _positive(software_nov["35_56"]),
        "L2_nov_3556_beats": _beats(software_nov["35_56"], software_lvl["35_56"]),
        "L3_des_3556_pos": _positive(des_conf["35_56"]),
        "L3_des_3556_beats": _beats(des_conf["35_56"], des_chg["35_56"]),
    }
    line1 = checks["L1_demand_front"] and checks["L1_guidance_front"]
    line2 = all(checks[k] for k in checks if k.startswith("L2_"))
    line3 = checks["L3_des_3556_pos"] and checks["L3_des_3556_beats"]
    payload = {
        "case_study_id": "horizon_anatomy_v1",
        "generated_at": meta.get("generated_at"),
        "n_core22": len(core22),
        "n_software": len(software),
        "n_designers": len(designers),
        "n_periods": len(periods),
        "n_late": len(late),
        "checks": checks,
        "line1": line1,
        "line2": line2,
        "line3": line3,
        "case_study_pass": line1 and line2 and line3,
        "demand_quant_core22": demand_quant,
        "guidance_surprise_core22": guidance_surprise,
        "software_novelty": software_nov,
        "software_level": software_lvl,
        "late_designers_confidence": des_conf,
        "late_designers_change": des_chg,
        "core22_competitive_change": core_chg,
    }
    out = history / "cross_company" / "json" / "horizon_anatomy_v1_20260818.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _mean(block: dict, horizon: str) -> float | None:
        return block[horizon]["rank_ic_mean"]

    print(
        json.dumps(
            {
                "case_study_id": "horizon_anatomy_v1",
                "generated_at": meta.get("generated_at"),
                "checks": checks,
                "line1": line1,
                "line2": line2,
                "line3": line3,
                "case_study_pass": line1 and line2 and line3,
                "demand_quant": {h: _mean(demand_quant, h) for h in HORIZONS},
                "guidance_surprise": {h: _mean(guidance_surprise, h) for h in HORIZONS},
                "software_novelty": {h: _mean(software_nov, h) for h in HORIZONS},
                "software_level": {h: _mean(software_lvl, h) for h in HORIZONS},
                "late_designers_conf": {h: _mean(des_conf, h) for h in HORIZONS},
                "late_designers_chg": {h: _mean(des_chg, h) for h in HORIZONS},
                "core22_change": {h: _mean(core_chg, h) for h in HORIZONS},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
