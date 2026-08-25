"""Stress-test the two live v2 objects: competitive change / software novelty,
and confidence level.

Indexed jackknife — same Spearman + summarizer as Rank IC Research.
Pre-registered in .memory/entries/expe-tech-lab-v3.md.
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
ODD = ("OPAL", "SPCX", "STRW")


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


def _periods_of(index: dict[IndexKey, dict[str, tuple[float, float]]], dimension: str, signal: str) -> list[str]:
    return sorted({period for dim, sig, period in index if dim == dimension and sig == signal})


def _score(html, spearman, index, tickers, *, dimension, signal, periods=None):
    want = {str(t).upper() for t in tickers}
    if periods is None:
        periods = _periods_of(index, dimension, signal)
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
    if universe == "all":
        return list(book)
    if universe == "all_minus_odd":
        return [t for t in book if t not in ODD]
    return [t for t in load_sector_companies(universe) if t.upper() in have]


def _jackknife(html, spearman, index, tickers, *, dimension, signal, periods):
    baseline = _score(
        html, spearman, index, tickers, dimension=dimension, signal=signal, periods=periods
    )
    folds = []
    for held in tickers:
        sub = [t for t in tickers if t != held]
        stats = _score(
            html, spearman, index, sub, dimension=dimension, signal=signal, periods=periods
        )
        mean = stats["rank_ic_mean"]
        base = baseline["rank_ic_mean"]
        folds.append(
            {
                "held_out": held,
                "rank_ic_mean": mean,
                "rank_ic_ir": stats["rank_ic_ir"],
                "n_periods": stats["n_periods"],
                "delta": None if mean is None or base is None else _round(float(mean) - float(base)),
            }
        )
    means = [f["rank_ic_mean"] for f in folds if f["rank_ic_mean"] is not None]
    return {
        "baseline": baseline,
        "n_tickers": len(tickers),
        "min_loo": _round(min(means)) if means else None,
        "max_loo": _round(max(means)) if means else None,
        "all_positive": bool(means) and all(m > 0 for m in means),
        "worst_held_out": min(folds, key=lambda f: f["rank_ic_mean"] or 99)["held_out"]
        if folds
        else None,
        "folds": folds,
    }


def _jk_beats(html, spearman, index, tickers, *, dimension, candidate, baseline, periods):
    rows = []
    wins = 0
    for held in tickers:
        sub = [t for t in tickers if t != held]
        cand = _score(
            html, spearman, index, sub, dimension=dimension, signal=candidate, periods=periods
        )
        base = _score(
            html, spearman, index, sub, dimension=dimension, signal=baseline, periods=periods
        )
        c, b = cand["rank_ic_mean"], base["rank_ic_mean"]
        beat = c is not None and b is not None and float(c) > float(b)
        if beat:
            wins += 1
        rows.append(
            {
                "held_out": held,
                "candidate": c,
                "baseline": b,
                "delta": None if c is None or b is None else _round(float(c) - float(b)),
                "beats": beat,
            }
        )
    return {
        "n": len(tickers),
        "n_beats": wins,
        "all_beat": wins == len(tickers) and len(tickers) > 0,
        "folds": rows,
    }


def _pair(html, spearman, index, tickers, *, dimension, candidate, baseline):
    periods = sorted(
        set(_periods_of(index, dimension, candidate)) & set(_periods_of(index, dimension, baseline))
    )
    cand = _score(
        html, spearman, index, tickers, dimension=dimension, signal=candidate, periods=periods
    )
    base = _score(
        html, spearman, index, tickers, dimension=dimension, signal=baseline, periods=periods
    )
    c, b = cand["rank_ic_mean"], base["rank_ic_mean"]
    return {
        "n_tickers": len(tickers),
        "overlap_n": len(periods),
        "candidate": cand,
        "baseline": base,
        "positive": c is not None and float(c) > 0,
        "beats": c is not None and b is not None and float(c) > float(b),
        "delta": None if c is None or b is None else _round(float(c) - float(b)),
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

    all_names = _resolve("all", book)
    core = _resolve("all_minus_odd", book)
    software = _resolve("software_cloud", book)
    software_pure = _resolve("software_pure", book)
    semis = _resolve("semis_cycle", book)
    designers = _resolve("designers", book)

    a_drop = _pair(
        html,
        spearman,
        index,
        core,
        dimension="competitive_position",
        candidate="change_magnitude",
        baseline="llm_level",
    )
    b_drop = _pair(
        html,
        spearman,
        index,
        core,
        dimension="management_confidence",
        candidate="llm_level",
        baseline="change_magnitude",
    )

    periods_chg = _periods_of(index, "competitive_position", "change_magnitude")
    periods_nov = sorted(
        set(_periods_of(index, "competitive_position", "narrative_novelty"))
        & set(_periods_of(index, "competitive_position", "llm_level"))
    )
    periods_conf = _periods_of(index, "management_confidence", "llm_level")

    a_jk_change = _jackknife(
        html,
        spearman,
        index,
        all_names,
        dimension="competitive_position",
        signal="change_magnitude",
        periods=periods_chg,
    )
    a_jk_nov = _jackknife(
        html,
        spearman,
        index,
        software,
        dimension="competitive_position",
        signal="narrative_novelty",
        periods=periods_nov,
    )
    a_jk_nov_vs_level = _jk_beats(
        html,
        spearman,
        index,
        software,
        dimension="competitive_position",
        candidate="narrative_novelty",
        baseline="llm_level",
        periods=periods_nov,
    )
    a_jk_pure = _jackknife(
        html,
        spearman,
        index,
        software_pure,
        dimension="competitive_position",
        signal="narrative_novelty",
        periods=periods_nov,
    )
    b_jk_all = _jackknife(
        html,
        spearman,
        index,
        all_names,
        dimension="management_confidence",
        signal="llm_level",
        periods=periods_conf,
    )
    b_jk_semis = _jackknife(
        html,
        spearman,
        index,
        semis,
        dimension="management_confidence",
        signal="llm_level",
        periods=periods_conf,
    )
    b_jk_software = _jackknife(
        html,
        spearman,
        index,
        software,
        dimension="management_confidence",
        signal="llm_level",
        periods=periods_conf,
    )
    b_jk_designers = _jackknife(
        html,
        spearman,
        index,
        designers,
        dimension="management_confidence",
        signal="llm_level",
        periods=periods_conf,
    )

    checks = {
        "A_drop_odd_positive": bool(a_drop["positive"]),
        "A_drop_odd_beats_level": bool(a_drop["beats"]),
        "A_jk_change_all_positive": bool(a_jk_change["all_positive"]),
        "A_jk_novelty_software_positive": bool(a_jk_nov["all_positive"]),
        "A_jk_novelty_beats_level": bool(a_jk_nov_vs_level["all_beat"]),
        "B_drop_odd_positive": bool(b_drop["positive"]),
        "B_drop_odd_beats_change": bool(b_drop["beats"]),
        "B_jk_all_positive": bool(b_jk_all["all_positive"]),
        "B_jk_semis_positive": bool(b_jk_semis["all_positive"]),
    }
    object_a = all(
        checks[k]
        for k in (
            "A_drop_odd_positive",
            "A_drop_odd_beats_level",
            "A_jk_change_all_positive",
            "A_jk_novelty_software_positive",
            "A_jk_novelty_beats_level",
        )
    )
    object_b = all(
        checks[k]
        for k in (
            "B_drop_odd_positive",
            "B_drop_odd_beats_change",
            "B_jk_all_positive",
            "B_jk_semis_positive",
        )
    )

    payload = {
        "case_study_id": "tech_lab_v3",
        "generated_at": meta.get("generated_at"),
        "label": LABEL,
        "horizon": HORIZON,
        "odd_dropped": list(ODD),
        "n_book": len(all_names),
        "n_core": len(core),
        "checks": checks,
        "object_a": object_a,
        "object_b": object_b,
        "case_study_pass": object_a and object_b,
        "object_a_detail": {
            "drop_odd": a_drop,
            "jk_change_all": a_jk_change,
            "jk_novelty_software": a_jk_nov,
            "jk_novelty_vs_level": a_jk_nov_vs_level,
            "jk_novelty_software_pure": a_jk_pure,
        },
        "object_b_detail": {
            "drop_odd": b_drop,
            "jk_all": b_jk_all,
            "jk_semis": b_jk_semis,
            "jk_software_control": b_jk_software,
            "jk_designers_ablation": b_jk_designers,
        },
    }
    out = history / "cross_company" / "json" / "tech_lab_stress_v3_20260818.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    summary = {
        k: payload[k]
        for k in (
            "case_study_id",
            "generated_at",
            "n_book",
            "n_core",
            "checks",
            "object_a",
            "object_b",
            "case_study_pass",
        )
    }
    summary["A_drop"] = a_drop
    summary["B_drop"] = b_drop
    summary["A_jk_change_range"] = [a_jk_change["min_loo"], a_jk_change["max_loo"], a_jk_change["worst_held_out"]]
    summary["A_jk_nov_range"] = [a_jk_nov["min_loo"], a_jk_nov["max_loo"], a_jk_nov["worst_held_out"]]
    summary["B_jk_all_range"] = [b_jk_all["min_loo"], b_jk_all["max_loo"], b_jk_all["worst_held_out"]]
    summary["B_jk_semis_range"] = [b_jk_semis["min_loo"], b_jk_semis["max_loo"], b_jk_semis["worst_held_out"]]
    summary["B_jk_software_control"] = [
        b_jk_software["min_loo"],
        b_jk_software["max_loo"],
        b_jk_software["worst_held_out"],
        b_jk_software["all_positive"],
    ]
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
