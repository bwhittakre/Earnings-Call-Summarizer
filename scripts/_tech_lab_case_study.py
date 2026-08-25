"""Score the tech Lab case-study recipes vs natural single-signal Rank IC.

Reads config/signal_packs/tech_lab_case_study_v1.yaml. Does not fit weights.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ingest.company_lists import load_sector_companies  # noqa: E402
from services.earnings_monitor.dashboard.lab_store import (  # noqa: E402
    load_lab_store,
    save_lab_store,
    universe_key,
    upsert_recipe,
)
from services.earnings_monitor.dashboard.rank_ic_lab import (  # noqa: E402
    blend_company_period,
)
from services.earnings_monitor.dashboard.rank_ic_research import (  # noqa: E402
    _rank_ic_html,
)
from services.earnings_monitor.dashboard.research_data import (  # noqa: E402
    load_rank_ic_bundle,
)
from services.earnings_monitor.dashboard.sectors import ALL_COMPANIES  # noqa: E402


def _round(value: object) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _resolve_tickers(universe: str, book: list[str]) -> list[str]:
    have = {t.upper() for t in book}
    if universe in {"all", ALL_COMPANIES, ""}:
        return list(book)
    sector = [str(t).upper() for t in load_sector_companies(universe)]
    return [t for t in sector if t in have]


def _score(
    html: object,
    rows: list[dict],
    tickers: list[str],
    *,
    label: str,
    horizon: str,
    dimension: str,
    signal: str,
    periods: list[str] | None = None,
) -> dict[str, object]:
    ics = html.period_rank_ics_for_selection(
        rows,
        tickers,
        label_key=label,
        horizon=horizon,
        dimension=dimension,
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


def _periods(rows: list[dict], *, label: str, horizon: str, dimension: str, signal: str) -> set[str]:
    out: set[str] = set()
    for row in rows:
        if str(row.get("label_key") or row.get("label") or "") != label:
            continue
        if str(row.get("horizon") or "") != horizon:
            continue
        if str(row.get("dimension") or "") != dimension:
            continue
        if str(row.get("signal") or "") != signal:
            continue
        period = str(row.get("period") or "")
        if period:
            out.add(period)
    return out


def main() -> None:
    spec_path = ROOT / "config" / "signal_packs" / "tech_lab_case_study_v1.yaml"
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    label = str(spec["label"])
    horizon = str(spec["horizon"])
    history = ROOT / "Structured Narrative" / "output"
    meta = json.loads(
        (history / "cross_company" / "json" / "narrative_signal_eval.json").read_text(
            encoding="utf-8"
        )
    )
    book = [str(t).upper() for t in (meta.get("tickers") or [])]
    rows = load_rank_ic_bundle(history_source=str(history)).company_period
    html = _rank_ic_html()
    store = load_lab_store()

    results: list[dict[str, object]] = []
    story_beats = 0
    story_n = 0
    for hyp in spec["hypotheses"]:
        tickers = _resolve_tickers(str(hyp["universe"]), book)
        dimension = str(hyp["dimension"])
        baseline = str(hyp["baseline_signal"])
        weights = {str(k): float(v) for k, v in dict(hyp["weights"]).items()}
        include_revision = bool(hyp.get("include_revision"))
        blended = blend_company_period(
            rows,
            tickers,
            label=label,
            horizon=horizon,
            dimension=dimension,
            weights=weights,
            include_revision=include_revision,
        )
        overlap = sorted(
            _periods(blended, label=label, horizon=horizon, dimension=dimension, signal="lab_blend")
            & _periods(rows, label=label, horizon=horizon, dimension=dimension, signal=baseline)
        )
        lab = _score(
            html,
            blended,
            tickers,
            label=label,
            horizon=horizon,
            dimension=dimension,
            signal="lab_blend",
            periods=overlap or None,
        )
        natural = _score(
            html,
            rows,
            tickers,
            label=label,
            horizon=horizon,
            dimension=dimension,
            signal=baseline,
            periods=overlap or None,
        )
        lab_ic = lab["rank_ic_mean"]
        nat_ic = natural["rank_ic_mean"]
        beats = (
            lab_ic is not None
            and nat_ic is not None
            and float(lab_ic) > float(nat_ic)
        )
        if not hyp.get("is_control"):
            story_n += 1
            if beats:
                story_beats += 1
        ukey = universe_key(
            ALL_COMPANIES if hyp["universe"] == "all" else str(hyp["universe"]),
            tickers,
        )
        upsert_recipe(
            store,
            name=str(hyp["title"]),
            universe_key_value=ukey,
            label=label,
            horizon=horizon,
            dimension=dimension,
            weights=weights,
            include_revision=include_revision,
            recipe_id=str(hyp["id"]),
        )
        results.append(
            {
                "id": hyp["id"],
                "title": hyp["title"],
                "universe": hyp["universe"],
                "tickers": tickers,
                "n_tickers": len(tickers),
                "dimension": dimension,
                "weights": weights,
                "baseline_signal": baseline,
                "is_control": bool(hyp.get("is_control")),
                "story": hyp["story"],
                "overlap_n": len(overlap),
                "lab": lab,
                "natural": natural,
                "beats_natural": beats,
                "delta": None
                if lab_ic is None or nat_ic is None
                else _round(float(lab_ic) - float(nat_ic)),
            }
        )

    save_lab_store(store)
    payload = {
        "case_study_id": spec["case_study_id"],
        "generated_at": meta.get("generated_at"),
        "label": label,
        "horizon": horizon,
        "n_tickers_book": len(book),
        "story_beats": story_beats,
        "story_n": story_n,
        "case_study_pass": story_beats >= 3,
        "results": results,
    }
    out = (
        history
        / "cross_company"
        / "json"
        / "tech_lab_case_study_v1_20260818.json"
    )
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
