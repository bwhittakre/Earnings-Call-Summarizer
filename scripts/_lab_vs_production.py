"""A-priori Lab blends vs production_v1 on the 17 Aug Rank IC book.

Uses the existing Lab blend + Research Rank IC summarizer. Does not fit weights.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.earnings_monitor.dashboard.rank_ic_lab import (  # noqa: E402
    CALL_DATE_SIGNALS,
    blend_company_period,
)
from services.earnings_monitor.dashboard.rank_ic_research import (  # noqa: E402
    _rank_ic_html,
    subset_leaderboard_rows,
)
from services.earnings_monitor.dashboard.research_data import load_rank_ic_bundle  # noqa: E402

LABEL = "asof"
HORIZON = "0_56"
DIMENSIONS = ("demand", "margins", "guidance")
PRODUCTION_PRIMARY = ("demand", "quant_z_pit")
PACK_SIGNALS = ("quant_z_pit", "agrees_with_quant")

RECIPES: dict[str, dict[str, float]] = {
    "quant_only": {"quant_z_pit": 1.0},
    "equal_call_date": {signal: 1.0 for signal in CALL_DATE_SIGNALS},
    "narrative_only": {
        "llm_level": 1.0,
        "change_magnitude": 1.0,
        "surprise_magnitude": 1.0,
        "narrative_novelty": 1.0,
    },
    "agreement_only": {"agrees_with_quant": 1.0},
    "quant_plus_agreement": {"quant_z_pit": 1.0, "agrees_with_quant": 1.0},
    "quant_plus_novelty": {"quant_z_pit": 1.0, "narrative_novelty": 1.0},
}


def _round(value: object) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def main() -> None:
    history = ROOT / "Structured Narrative" / "output"
    meta_path = history / "cross_company" / "json" / "narrative_signal_eval.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    bundle = load_rank_ic_bundle(history_source=str(history))
    tickers = [str(t).upper() for t in (meta.get("tickers") or [])]
    rows = bundle.company_period
    if not rows:
        raise SystemExit("company_period is empty")

    production: list[dict[str, object]] = []
    for dimension in DIMENSIONS:
        scored = subset_leaderboard_rows(
            rows,
            tickers,
            label=LABEL,
            horizon=HORIZON,
            dimension=dimension,
            signals=list(PACK_SIGNALS),
        )
        for item in scored:
            production.append(
                {
                    "kind": "production",
                    "recipe": f"{item['signal']}",
                    "dimension": dimension,
                    "rank_ic_mean": _round(item.get("rank_ic_mean")),
                    "rank_ic_ir": _round(item.get("rank_ic_ir")),
                    "hit_rate": _round(item.get("positive_rank_ic_hit_rate")),
                    "n_periods": item.get("n_periods"),
                }
            )

    blends: list[dict[str, object]] = []
    for name, weights in RECIPES.items():
        for dimension in DIMENSIONS:
            blended = blend_company_period(
                rows,
                tickers,
                label=LABEL,
                horizon=HORIZON,
                dimension=dimension,
                weights=weights,
            )
            scored = subset_leaderboard_rows(
                blended,
                tickers,
                label=LABEL,
                horizon=HORIZON,
                dimension=dimension,
                signals=["lab_blend"],
            )
            item = scored[0] if scored else {}
            blends.append(
                {
                    "kind": "lab_blend",
                    "recipe": name,
                    "dimension": dimension,
                    "rank_ic_mean": _round(item.get("rank_ic_mean")),
                    "rank_ic_ir": _round(item.get("rank_ic_ir")),
                    "hit_rate": _round(item.get("positive_rank_ic_hit_rate")),
                    "n_periods": item.get("n_periods"),
                    "n_blend_rows": len(blended),
                }
            )

    primary = next(
        row
        for row in production
        if row["dimension"] == PRODUCTION_PRIMARY[0]
        and row["recipe"] == PRODUCTION_PRIMARY[1]
    )
    primary_ic = primary["rank_ic_mean"]
    winners = [
        row
        for row in blends
        if row["dimension"] == "demand"
        and row["recipe"] != "quant_only"
        and row["rank_ic_mean"] is not None
        and primary_ic is not None
        and float(row["rank_ic_mean"]) > float(primary_ic)
    ]

    html = _rank_ic_html()
    demand_blend_periods: dict[str, set[str]] = {}
    for name, weights in RECIPES.items():
        blended = blend_company_period(
            rows,
            tickers,
            label=LABEL,
            horizon=HORIZON,
            dimension="demand",
            weights=weights,
        )
        demand_blend_periods[name] = {
            str(item.get("period") or "")
            for item in blended
            if item.get("period")
        }
    production_periods = {
        str(row.get("period") or "")
        for row in rows
        if str(row.get("label_key") or row.get("label") or "") == LABEL
        and str(row.get("horizon") or "") == HORIZON
        and str(row.get("dimension") or "") == "demand"
        and str(row.get("signal") or "") == "quant_z_pit"
        and row.get("period")
    }
    overlap = set.intersection(
        production_periods,
        demand_blend_periods["equal_call_date"],
        demand_blend_periods["narrative_only"],
        demand_blend_periods["quant_only"],
    )
    overlap_list = sorted(overlap)

    def _score_on_periods(signal: str, source_rows: list[dict[str, object]], periods: list[str]) -> dict[str, object]:
        ics = html.period_rank_ics_for_selection(
            source_rows,
            tickers,
            label_key=LABEL,
            horizon=HORIZON,
            dimension="demand",
            signal=signal,
            periods=periods,
        )
        stats = html.summarize_period_rank_ics(ics)
        return {
            "rank_ic_mean": _round(stats.get("rank_ic_mean")),
            "rank_ic_ir": _round(stats.get("rank_ic_ir")),
            "hit_rate": _round(stats.get("positive_rank_ic_hit_rate")),
            "n_periods": stats.get("n_periods"),
        }

    overlap_scores: list[dict[str, object]] = [
        {
            "kind": "production_overlap",
            "recipe": "quant_z_pit",
            "dimension": "demand",
            **_score_on_periods("quant_z_pit", rows, overlap_list),
        }
    ]
    for name, weights in RECIPES.items():
        blended = blend_company_period(
            rows,
            tickers,
            label=LABEL,
            horizon=HORIZON,
            dimension="demand",
            weights=weights,
        )
        overlap_scores.append(
            {
                "kind": "lab_blend_overlap",
                "recipe": name,
                "dimension": "demand",
                **_score_on_periods("lab_blend", blended, overlap_list),
            }
        )
    overlap_primary = next(
        row for row in overlap_scores if row["kind"] == "production_overlap"
    )
    overlap_primary_ic = overlap_primary["rank_ic_mean"]
    overlap_winners = [
        row
        for row in overlap_scores
        if row["kind"] == "lab_blend_overlap"
        and row["recipe"] != "quant_only"
        and row["rank_ic_mean"] is not None
        and overlap_primary_ic is not None
        and float(row["rank_ic_mean"]) > float(overlap_primary_ic)
    ]

    payload = {
        "generated_at": meta.get("generated_at"),
        "n_tickers": len(tickers),
        "tickers": tickers,
        "label": LABEL,
        "horizon": HORIZON,
        "primary": primary,
        "lab_blend_beats_primary": bool(winners),
        "winning_demand_recipes": [row["recipe"] for row in winners],
        "production": production,
        "blends": blends,
        "overlap_n_periods": len(overlap_list),
        "overlap_periods": overlap_list,
        "lab_blend_beats_primary_36overlap": bool(overlap_winners),
        "winning_demand_recipes_36overlap": [row["recipe"] for row in overlap_winners],
        "overlap_primary": overlap_primary,
        "overlap_scores": overlap_scores,
    }
    out = ROOT / "Structured Narrative" / "output" / "cross_company" / "json" / "lab_vs_production_20260818.json"
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
