"""Path ID v1: T+14 first-print regime on the locked 17 Aug book.

Pre-registered in .memory/entries/expe-path-id-v1.md.
Refuse to run unless generated_at matches the locked stamp.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LOCKED_GENERATED_AT = "2026-08-17T17:28:40+00:00"
LABEL = "asof"
DIMENSION = "competitive_position"
SIGNAL = "narrative_novelty"
BUCKETS = ("0_14", "14_35", "35_56")
SPLIT = "asof-path-id-17aug-book-v1"
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


def assert_locked_stamp(generated_at: object) -> None:
    stamp = str(generated_at or "")
    if stamp != LOCKED_GENERATED_AT:
        raise SystemExit(
            f"path_id_v1 refuses stamp {stamp!r}; locked {LOCKED_GENERATED_AT!r}"
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


def _zscore(values: list[float]) -> list[float] | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    if var <= 0 or var != var:
        return None
    std = math.sqrt(var)
    return [(v - mean) / std for v in values]


def top_tercile_tickers(returns: dict[str, float]) -> set[str]:
    """Highest ceil(n/3) names by 0_14 return."""
    if not returns:
        return set()
    n = len(returns)
    k = math.ceil(n / 3)
    ranked = sorted(returns.items(), key=lambda kv: kv[1], reverse=True)
    return {ticker for ticker, _ in ranked[:k]}


def median_value(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (float(ordered[mid - 1]) + float(ordered[mid])) / 2.0


def path_signal_map(
    novelty: dict[str, float],
    top_tercile: set[str],
) -> dict[str, float] | None:
    """z(novelty) * (+1 if not top tercile else -1). None if z-score undefined."""
    tickers = sorted(novelty)
    zvals = _zscore([novelty[t] for t in tickers])
    if zvals is None:
        return None
    out: dict[str, float] = {}
    for ticker, zval in zip(tickers, zvals, strict=True):
        sign = -1.0 if ticker in top_tercile else 1.0
        out[ticker] = zval * sign
    return out


def predict_path(
    *,
    in_top_tercile: bool,
    novelty: float,
    novelty_median: float,
) -> str:
    if in_top_tercile:
        return "0_14"
    if novelty >= novelty_median:
        return "14_35"
    return "35_56"


def ex_post_path(r014: float, rmid: float, rlate: float) -> str | None:
    """Argmax of the three bucket returns. None on a tie."""
    vals = {"0_14": r014, "14_35": rmid, "35_56": rlate}
    best = max(vals.values())
    winners = [name for name, value in vals.items() if value == best]
    if len(winners) != 1:
        return None
    return winners[0]


def _mean_ic(ics: list[float | None]) -> float | None:
    vals = [float(x) for x in ics if x is not None]
    return _round(sum(vals) / len(vals)) if vals else None


def _index_rows(rows, *, label: str) -> dict[tuple[str, str, str, str], dict[str, tuple[float, float]]]:
    out: dict[tuple[str, str, str, str], dict[str, tuple[float, float]]] = {}
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


def _pairs(index, tickers, *, period: str, horizon: str):
    want = {str(t).upper() for t in tickers}
    raw = index.get((DIMENSION, SIGNAL, period, horizon)) or {}
    return {t: raw[t] for t in want if t in raw}


def _ic(spearman, xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 3:
        return None
    return spearman(xs, ys)


def _evaluate_line1(
    spearman,
    common: list[str],
    by_h: dict[str, dict[str, tuple[float, float]]],
    drop: set[str] | None = None,
) -> tuple[float | None, float | None]:
    names = [t for t in common if not drop or t not in drop]
    novelty = {t: by_h["0_14"][t][0] for t in names}
    rets = {t: by_h["0_14"][t][1] for t in names}
    signals = path_signal_map(novelty, top_tercile_tickers(rets))
    if signals is None:
        return None, None
    mid = [by_h["14_35"][t][1] for t in names]
    path_ic = _round(_ic(spearman, [signals[t] for t in names], mid))
    raw_ic = _round(_ic(spearman, [novelty[t] for t in names], mid))
    return path_ic, raw_ic


def main() -> None:
    sys.path.insert(0, str(ROOT))
    from src.ingest.company_lists import load_sector_companies
    from services.earnings_monitor.dashboard.rank_ic_research import _spearman
    from services.earnings_monitor.dashboard.research_data import load_rank_ic_bundle

    history = ROOT / "Structured Narrative" / "output"
    meta = json.loads(
        (history / "cross_company" / "json" / "narrative_signal_eval.json").read_text(
            encoding="utf-8"
        )
    )
    assert_locked_stamp(meta.get("generated_at"))
    book = {str(t).upper() for t in (meta.get("tickers") or [])}
    software = [t.upper() for t in load_sector_companies("software_cloud") if t.upper() in book]
    rows = load_rank_ic_bundle(history_source=str(history)).company_period
    spearman = _spearman()
    index = _index_rows(rows, label=LABEL)

    periods_out: list[dict] = []
    path_ics: list[float | None] = []
    raw_ics: list[float | None] = []
    subset_ics: list[float | None] = []
    full_ics: list[float | None] = []
    hits = 0
    scored_paths = 0
    later_hits = 0
    later_scored = 0
    name_paths: list[dict[str, object]] = []
    jack_adsk: list[float | None] = []
    jack_intu: list[float | None] = []
    jack_adsk_raw: list[float | None] = []
    jack_intu_raw: list[float | None] = []

    for period in LATE:
        by_h = {h: _pairs(index, software, period=period, horizon=h) for h in BUCKETS}
        common = sorted(set(by_h["0_14"]) & set(by_h["14_35"]) & set(by_h["35_56"]))
        rets_014 = {t: by_h["0_14"][t][1] for t in common}
        novelty = {t: by_h["0_14"][t][0] for t in common}
        top = top_tercile_tickers(rets_014)
        nov_median = median_value(list(novelty.values())) if novelty else None

        path_ic, raw_ic = _evaluate_line1(spearman, common, by_h)
        path_ics.append(path_ic)
        raw_ics.append(raw_ic)
        adsk_p, adsk_r = _evaluate_line1(spearman, common, by_h, drop={"ADSK"})
        intu_p, intu_r = _evaluate_line1(spearman, common, by_h, drop={"INTU"})
        jack_adsk.append(adsk_p)
        jack_adsk_raw.append(adsk_r)
        jack_intu.append(intu_p)
        jack_intu_raw.append(intu_r)

        period_hits = 0
        period_scored = 0
        for ticker in common:
            realized = ex_post_path(
                by_h["0_14"][ticker][1],
                by_h["14_35"][ticker][1],
                by_h["35_56"][ticker][1],
            )
            if realized is None or nov_median is None:
                continue
            predicted = predict_path(
                in_top_tercile=ticker in top,
                novelty=novelty[ticker],
                novelty_median=nov_median,
            )
            period_scored += 1
            scored_paths += 1
            if predicted == realized:
                period_hits += 1
                hits += 1
            later_scored += 1
            predicted_later = predicted != "0_14"
            realized_later = realized != "0_14"
            if predicted_later == realized_later:
                later_hits += 1
            name_paths.append(
                {
                    "period": period,
                    "ticker": ticker,
                    "predicted": predicted,
                    "realized": realized,
                    "hit": predicted == realized,
                }
            )

        later_names = [t for t in common if t not in top]
        subset_ic = None
        full_ic = None
        if len(common) >= 5 and len(later_names) >= 5:
            full_ic = _round(
                _ic(
                    spearman,
                    [by_h["0_14"][t][0] for t in common],
                    [by_h["14_35"][t][1] for t in common],
                )
            )
            subset_ic = _round(
                _ic(
                    spearman,
                    [by_h["0_14"][t][0] for t in later_names],
                    [by_h["14_35"][t][1] for t in later_names],
                )
            )
        subset_ics.append(subset_ic)
        full_ics.append(full_ic)

        both_l1 = path_ic is not None and raw_ic is not None
        periods_out.append(
            {
                "period": period,
                "n_common": len(common),
                "n_top_tercile": len(top),
                "n_later": len(later_names),
                "path_ic_14_35": path_ic,
                "novelty_ic_14_35": raw_ic,
                "l1_both_finite": both_l1,
                "subset_novelty_ic_14_35": subset_ic,
                "full_novelty_ic_14_35": full_ic,
                "path_hits": period_hits,
                "path_scored": period_scored,
            }
        )

    l1_both = [
        i
        for i, (a, b) in enumerate(zip(path_ics, raw_ics, strict=True))
        if a is not None and b is not None
    ]
    mean_path = _mean_ic([path_ics[i] for i in l1_both])
    mean_raw = _mean_ic([raw_ics[i] for i in l1_both])
    l1 = (
        mean_path is not None
        and mean_raw is not None
        and len(l1_both) >= 15
        and float(mean_path) > float(mean_raw)
    )

    hit_rate = _round(hits / scored_paths) if scored_paths else None
    l2 = hit_rate is not None and float(hit_rate) >= 0.45
    later_rate = _round(later_hits / later_scored) if later_scored else None

    l3_both = [
        i
        for i, (a, b) in enumerate(zip(subset_ics, full_ics, strict=True))
        if a is not None and b is not None
    ]
    mean_subset = _mean_ic([subset_ics[i] for i in l3_both])
    mean_full = _mean_ic([full_ics[i] for i in l3_both])
    l3 = (
        mean_subset is not None
        and mean_full is not None
        and len(l3_both) >= 15
        and float(mean_subset) > float(mean_full)
    )

    checks = {
        "L1_path_beats_novelty_14_35": l1,
        "L2_hit_rate_ge_045": l2,
        "L3_later_subset_beats_full_14_35": l3,
    }
    payload = {
        "case_study_id": "path_id_v1",
        "generated_at": meta.get("generated_at"),
        "split": SPLIT,
        "checks": checks,
        "line1": l1,
        "line2": l2,
        "line3": l3,
        "case_study_pass": all(checks.values()),
        "l1_periods_finite": len(l1_both),
        "mean_path_ic_14_35": mean_path,
        "mean_novelty_ic_14_35": mean_raw,
        "hit_rate": hit_rate,
        "path_hits": hits,
        "path_scored": scored_paths,
        "front_vs_later_hit_rate": later_rate,
        "l3_periods_finite": len(l3_both),
        "mean_subset_novelty_ic_14_35": mean_subset,
        "mean_full_novelty_ic_14_35": mean_full,
        "jackknife": {
            "drop_ADSK_mean_path_ic": _mean_ic(jack_adsk),
            "drop_ADSK_mean_novelty_ic": _mean_ic(jack_adsk_raw),
            "drop_INTU_mean_path_ic": _mean_ic(jack_intu),
            "drop_INTU_mean_novelty_ic": _mean_ic(jack_intu_raw),
        },
        "software": software,
        "name_paths": name_paths,
        "periods": periods_out,
    }
    out = history / "cross_company" / "json" / "path_id_v1.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "case_study_id": "path_id_v1",
                "generated_at": payload["generated_at"],
                "split": SPLIT,
                "checks": checks,
                "case_study_pass": payload["case_study_pass"],
                "l1": {
                    "periods": len(l1_both),
                    "mean_path_ic": mean_path,
                    "mean_novelty_ic": mean_raw,
                },
                "l2": {"hit_rate": hit_rate, "hits": hits, "scored": scored_paths},
                "l3": {
                    "periods": len(l3_both),
                    "mean_subset_ic": mean_subset,
                    "mean_full_ic": mean_full,
                },
                "jackknife": payload["jackknife"],
                "front_vs_later_hit_rate": later_rate,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
