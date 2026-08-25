"""Term structure v3: period-level late 0_56 premium and noise cancellation.

Pre-registered in .memory/entries/expe-term-structure-v3.md.
"""
from __future__ import annotations

import json
import math
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
DIMENSION = "competitive_position"
SIGNAL = "narrative_novelty"
BUCKETS = ("0_14", "14_35", "35_56")
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


def _zscore(values: list[float]) -> list[float] | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
    if var <= 0 or var != var:
        return None
    std = math.sqrt(var)
    return [(v - mean) / std for v in values]


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


def _pairs(index, tickers, *, period, horizon):
    want = {str(t).upper() for t in tickers}
    raw = index.get((DIMENSION, SIGNAL, period, horizon)) or {}
    return {t: raw[t] for t in want if t in raw}


def _ic(spearman, pairs: dict[str, tuple[float, float]]):
    if len(pairs) < 3:
        return None
    xs = [p[0] for p in pairs.values()]
    ys = [p[1] for p in pairs.values()]
    return spearman(xs, ys)


def _common(a: dict, b: dict):
    keys = sorted(set(a) & set(b))
    return keys


def main() -> None:
    history = ROOT / "Structured Narrative" / "output"
    meta = json.loads(
        (history / "cross_company" / "json" / "narrative_signal_eval.json").read_text(
            encoding="utf-8"
        )
    )
    book = {str(t).upper() for t in (meta.get("tickers") or [])}
    software = [t for t in load_sector_companies("software_cloud") if t.upper() in book]
    rows = load_rank_ic_bundle(history_source=str(history)).company_period
    html = _rank_ic_html()
    spearman = _spearman()
    index = _index_rows(rows, label=LABEL)

    periods_out = []
    premium_flags: list[bool | None] = []
    pair_corrs: list[float] = []
    ic_014: list[float | None] = []
    ic_mid: list[float | None] = []
    ic_356: list[float | None] = []
    ic_056: list[float | None] = []
    ic_zsum: list[float | None] = []

    for period in LATE:
        by_h = {h: _pairs(index, software, period=period, horizon=h) for h in (*BUCKETS, "0_56")}
        ics = {h: _round(_ic(spearman, by_h[h])) for h in by_h}
        buckets_ok = all(ics[h] is not None for h in BUCKETS)
        combined_ok = ics["0_56"] is not None
        premium = None
        if buckets_ok and combined_ok:
            premium = float(ics["0_56"]) > max(float(ics[h]) for h in BUCKETS)
        premium_flags.append(premium)
        ic_014.append(ics["0_14"])
        ic_mid.append(ics["14_35"])
        ic_356.append(ics["35_56"])
        ic_056.append(ics["0_56"])

        pair_vals = []
        for a, b in (("0_14", "14_35"), ("0_14", "35_56"), ("14_35", "35_56")):
            keys = _common(by_h[a], by_h[b])
            if len(keys) < 3:
                continue
            corr = spearman([by_h[a][k][1] for k in keys], [by_h[b][k][1] for k in keys])
            if corr is not None:
                pair_vals.append(float(corr))
        period_pair_mean = _round(sum(pair_vals) / len(pair_vals)) if pair_vals else None
        if period_pair_mean is not None:
            pair_corrs.append(float(period_pair_mean))

        common = sorted(set(by_h["0_14"]) & set(by_h["14_35"]) & set(by_h["35_56"]))
        zsum_ic = None
        if len(common) >= 3:
            cols = {h: [by_h[h][t][1] for t in common] for h in BUCKETS}
            zcols = {h: _zscore(cols[h]) for h in BUCKETS}
            if all(zcols[h] is not None for h in BUCKETS):
                zsum = [
                    zcols["0_14"][i] + zcols["14_35"][i] + zcols["35_56"][i]
                    for i in range(len(common))
                ]
                sig = [by_h["0_56"].get(t, by_h["0_14"][t])[0] for t in common]
                zsum_ic = _round(spearman(sig, zsum))
        ic_zsum.append(zsum_ic)

        periods_out.append(
            {
                "period": period,
                "n": {h: len(by_h[h]) for h in by_h},
                "ic": ics,
                "premium": premium,
                "bucket_return_pair_mean": period_pair_mean,
                "zsum_ic": zsum_ic,
            }
        )

    scored_premium = [f for f in premium_flags if f is not None]
    premium_hits = sum(1 for f in scored_premium if f)
    pair_mean = _round(sum(pair_corrs) / len(pair_corrs)) if pair_corrs else None
    bucket_mean = html.summarize_period_rank_ics(
        [
            None
            if a is None or b is None or c is None
            else (float(a) + float(b) + float(c)) / 3
            for a, b, c in zip(ic_014, ic_mid, ic_356, strict=True)
        ]
    )
    # Mean of the three bucket *means* (each horizon's mean IC), not mean of
    # per-period averages — Line 3 compares to the mean of the three bucket ICs.
    def _mean_ic(ics: list[float | None]) -> float | None:
        vals = [float(x) for x in ics if x is not None]
        return _round(sum(vals) / len(vals)) if vals else None

    mean_014 = _mean_ic(ic_014)
    mean_mid = _mean_ic(ic_mid)
    mean_356 = _mean_ic(ic_356)
    mean_056 = _mean_ic(ic_056)
    mean_zsum = _mean_ic(ic_zsum)
    mean_of_buckets = None
    if mean_014 is not None and mean_mid is not None and mean_356 is not None:
        mean_of_buckets = _round((float(mean_014) + float(mean_mid) + float(mean_356)) / 3)

    checks = {
        "L1_premium_ge_12": premium_hits >= 12 and len(scored_premium) >= 12,
        "L2_pair_mean_lt_050": pair_mean is not None and float(pair_mean) < 0.50,
        "L3_zsum_beats_bucket_mean": (
            mean_zsum is not None
            and mean_of_buckets is not None
            and float(mean_zsum) > float(mean_of_buckets)
        ),
    }
    payload = {
        "case_study_id": "term_structure_v3",
        "generated_at": meta.get("generated_at"),
        "checks": checks,
        "line1": checks["L1_premium_ge_12"],
        "line2": checks["L2_pair_mean_lt_050"],
        "line3": checks["L3_zsum_beats_bucket_mean"],
        "case_study_pass": all(checks.values()),
        "premium_hits": premium_hits,
        "premium_scored": len(scored_premium),
        "bucket_return_pair_mean": pair_mean,
        "mean_ic": {
            "0_14": mean_014,
            "14_35": mean_mid,
            "35_56": mean_356,
            "0_56": mean_056,
            "zsum": mean_zsum,
            "mean_of_three_buckets": mean_of_buckets,
        },
        "periods": periods_out,
    }
    out = history / "cross_company" / "json" / "term_structure_v3_20260818.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "case_study_id": "term_structure_v3",
                "generated_at": meta.get("generated_at"),
                "checks": checks,
                "case_study_pass": payload["case_study_pass"],
                "premium": [premium_hits, len(scored_premium)],
                "pair_mean": pair_mean,
                "mean_ic": payload["mean_ic"],
                "premium_periods": [p["period"] for p in periods_out if p["premium"]],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
