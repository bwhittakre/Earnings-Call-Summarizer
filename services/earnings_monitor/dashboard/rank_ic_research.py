"""Native Rank IC Research workbench: Explore (six) + Explain (four).

Read-only production pack. Lab (weights and saved recipes) is a separate page.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .company_labels import format_company_label
from .data import DashboardData
from .research_data import (
    HORIZON_ORDER,
    RankIcBundle,
    filter_rank_ic_rows,
    import_sn,
    load_rank_ic_bundle,
    unique_sorted,
)
from .sectors import is_full_universe

ALL_MEAN = "ALL_MEAN"
DEFAULT_LABEL = "asof"
DEFAULT_HORIZON = "0_56"
HORIZON_KEYS = HORIZON_ORDER
MIN_CROSS_SECTION = 3

EXPLORE_ORDER = (
    "Period heatmap",
    "Company × quarter",
    "Leaderboard",
    "By dimension",
    "Agreement effect",
    "Jackknife",
)
EXPLAIN_ORDER = (
    "Quarter drivers",
    "Measure drill-down",
    "Horizon fingerprint",
    "Street overlay",
)

_SIGNAL_LABELS = {
    "llm_level": "Level",
    "change_magnitude": "Delta",
    "surprise_magnitude": "Surprise",
    "narrative_novelty": "Novelty",
    "quant_z_pit": "Quant z (PIT)",
    "quant_guidance_revision_z_pit": "Guidance rev z (T+7)",
    "narrative_quant_gap": "Narrative−quant gap",
    "agrees_with_quant": "Agrees with quant",
    "evidence_confidence": "Evidence confidence",
}
_DIMENSION_LABELS = {
    "demand": "Demand",
    "margins": "Margins",
    "earnings_power": "Earnings power",
    "capital_allocation": "Capital allocation",
    "guidance": "Guidance",
    "management_confidence": "Management confidence",
    "competitive_position": "Competitive position",
    "macro_regulatory_risk": "Macro / regulatory risk",
    ALL_MEAN: "All dimensions (mean, display-only)",
}
_LABEL_DISPLAY = {
    "event": "Event (T+7 entry, earnings-date bucketed)",
    "asof": "As-of (investable, primary)",
    "custom": "Custom label",
}


@dataclass(frozen=True)
class RankIcFilters:
    label: str
    horizon: str
    dimension: str
    signal: str
    universe: list[str]
    full_universe: bool


def _finite(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def _rank_ic_html():
    return import_sn("rank_ic_html")


def _spearman():
    return import_sn("spearman_ic").spearman_rank_ic


def signal_label(signal: str) -> str:
    return _SIGNAL_LABELS.get(signal, signal)


def dimension_label(dimension: str) -> str:
    return _DIMENSION_LABELS.get(dimension, dimension)


def label_display(label: str) -> str:
    return _LABEL_DISPLAY.get(label, label)


def all_mean_blocked_message() -> str:
    return (
        "ALL_MEAN has no per-period cross-section by design — pooling every "
        "dimension into one cross-section is the unit-of-observation bug that "
        "was fixed. Pick a real dimension, or use By dimension for the full "
        "breakdown."
    )


def _universe(
    data: DashboardData, sector_tickers: Sequence[str] | None
) -> list[str]:
    if sector_tickers is not None:
        return [str(ticker).upper() for ticker in sector_tickers]
    return list(data.tickers)


def _sort_periods(periods: Sequence[str], *, period_col: str | None = None) -> list[str]:
    values = [str(p) for p in periods if str(p).strip()]
    try:
        return _rank_ic_html().sort_periods(values, period_col or "period_end_calendar_quarter")
    except Exception:  # noqa: BLE001
        return sorted(values)


def _fmt(value: Any, digits: int = 3) -> str:
    number = _finite(value)
    if number is None:
        return "—"
    return f"{number:+.{digits}f}"


def _table(st: Any, rows: list[dict[str, Any]], *, height: int | None = None) -> None:
    if not rows:
        st.info("No matching records.")
        return
    kwargs: dict[str, Any] = {"use_container_width": True, "hide_index": True}
    if height is not None:
        kwargs["height"] = height
    try:
        import pandas as pd  # type: ignore

        st.dataframe(pd.DataFrame(rows), **kwargs)
    except Exception:  # noqa: BLE001
        st.dataframe(rows, **kwargs)


def _plotly_chart(st: Any, figure: Any, *, key: str) -> None:
    try:
        st.plotly_chart(figure, use_container_width=True, key=key)
    except TypeError:
        st.plotly_chart(figure, use_container_width=True)


def real_dimensions(rows: Sequence[dict[str, Any]]) -> list[str]:
    dims = unique_sorted(list(rows), "dimension")
    return [d for d in dims if d != ALL_MEAN]


def periods_for_cell(
    company_period: list[dict[str, Any]],
    *,
    label: str,
    horizon: str,
    dimension: str | None = None,
    signal: str | None = None,
) -> list[str]:
    rows = filter_rank_ic_rows(
        company_period,
        label_key=label,
        horizon=horizon,
        dimension=dimension,
        signal=signal,
    )
    seen: list[str] = []
    for row in rows:
        period = str(row.get("period") or "")
        if period and period not in seen:
            seen.append(period)
    period_col = None
    if rows:
        period_col = str(rows[0].get("period_col") or "") or None
    return _sort_periods(seen, period_col=period_col)


def subset_period_ic_rows(
    company_period: list[dict[str, Any]],
    tickers: Sequence[str],
    *,
    label: str,
    horizon: str,
    dimension: str,
    signals: Sequence[str],
    periods: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    html = _rank_ic_html()
    period_list = list(periods) if periods is not None else None
    out: list[dict[str, Any]] = []
    for signal in signals:
        ics = html.period_rank_ics_for_selection(
            company_period,
            list(tickers),
            label_key=label,
            horizon=horizon,
            dimension=dimension,
            signal=signal,
            periods=period_list,
        )
        used_periods = period_list or periods_for_cell(
            company_period, label=label, horizon=horizon, dimension=dimension, signal=signal
        )
        for period, rank_ic in zip(used_periods, ics):
            if rank_ic is None:
                continue
            n = sum(
                1
                for row in company_period
                if str(row.get("label_key")) == label
                and str(row.get("horizon")) == horizon
                and str(row.get("dimension")) == dimension
                and str(row.get("signal")) == signal
                and str(row.get("period")) == period
                and str(row.get("ticker") or "").upper() in {t.upper() for t in tickers}
                and _finite(row.get("signal_mean")) is not None
                and _finite(row.get("label_mean")) is not None
            )
            out.append(
                {
                    "label_key": label,
                    "horizon": horizon,
                    "dimension": dimension,
                    "signal": signal,
                    "period": period,
                    "n": n,
                    "rank_ic": rank_ic,
                    "ic": None,
                }
            )
    return out


def subset_leaderboard_rows(
    company_period: list[dict[str, Any]],
    tickers: Sequence[str],
    *,
    label: str,
    horizon: str,
    dimension: str,
    signals: Sequence[str],
) -> list[dict[str, Any]]:
    html = _rank_ic_html()
    rows: list[dict[str, Any]] = []
    for signal in signals:
        ics = html.period_rank_ics_for_selection(
            company_period,
            list(tickers),
            label_key=label,
            horizon=horizon,
            dimension=dimension,
            signal=signal,
        )
        stats = html.summarize_period_rank_ics(ics)
        rows.append(
            {
                "signal": signal,
                "label": label,
                "horizon": horizon,
                "dimension": dimension,
                "rank_ic_mean": stats.get("rank_ic_mean"),
                "rank_ic_ir": stats.get("rank_ic_ir"),
                "positive_rank_ic_hit_rate": stats.get("positive_rank_ic_hit_rate"),
                "n_periods": stats.get("n_periods"),
                "n_rows": None,
                "universe": "selection",
            }
        )
    rows.sort(
        key=lambda r: (
            -(r["rank_ic_mean"] if r["rank_ic_mean"] is not None else -999),
            str(r["signal"]),
        )
    )
    return rows


def subset_dimension_matrix(
    company_period: list[dict[str, Any]],
    tickers: Sequence[str],
    *,
    label: str,
    horizon: str,
    dimensions: Sequence[str],
    signals: Sequence[str],
) -> list[dict[str, Any]]:
    html = _rank_ic_html()
    rows: list[dict[str, Any]] = []
    for dimension in dimensions:
        if dimension == ALL_MEAN:
            continue
        for signal in signals:
            ics = html.period_rank_ics_for_selection(
                company_period,
                list(tickers),
                label_key=label,
                horizon=horizon,
                dimension=dimension,
                signal=signal,
            )
            stats = html.summarize_period_rank_ics(ics)
            rows.append(
                {
                    "dimension": dimension,
                    "signal": signal,
                    "rank_ic_mean": stats.get("rank_ic_mean"),
                    "rank_ic_ir": stats.get("rank_ic_ir"),
                    "positive_rank_ic_hit_rate": stats.get("positive_rank_ic_hit_rate"),
                    "n_periods": stats.get("n_periods"),
                }
            )
    return rows


def period_leave_one_out(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """This-quarter autopsy: Spearman Rank IC leave-one-ticker-out Δ.

    ``delta`` = IC(without ticker) − IC(all). Positive means the held-out name
    was dragging the period Rank IC down.
    """
    spearman = _spearman()
    usable = [
        row
        for row in rows
        if _finite(row.get("signal_mean")) is not None
        and _finite(row.get("label_mean")) is not None
        and str(row.get("ticker") or "").strip()
    ]
    xs = [float(row["signal_mean"]) for row in usable]
    ys = [float(row["label_mean"]) for row in usable]
    baseline = spearman(xs, ys)
    sig_order = sorted(range(len(usable)), key=lambda i: xs[i], reverse=True)
    ret_order = sorted(range(len(usable)), key=lambda i: ys[i], reverse=True)
    sig_rank = {idx: rank + 1 for rank, idx in enumerate(sig_order)}
    ret_rank = {idx: rank + 1 for rank, idx in enumerate(ret_order)}
    out: list[dict[str, Any]] = []
    for i, row in enumerate(usable):
        fold = spearman(xs[:i] + xs[i + 1 :], ys[:i] + ys[i + 1 :])
        delta = None
        if fold is not None and baseline is not None:
            delta = float(fold) - float(baseline)
        out.append(
            {
                "ticker": str(row.get("ticker")).upper(),
                "signal_mean": xs[i],
                "label_mean": ys[i],
                "signal_rank": sig_rank[i],
                "return_rank": ret_rank[i],
                "loo_rank_ic": fold,
                "loo_delta": delta,
                "baseline_rank_ic": baseline,
                "n": len(usable),
            }
        )
    out.sort(key=lambda r: (r["signal_rank"], r["ticker"]))
    return out


def horizon_fingerprint(
    company_period: list[dict[str, Any]],
    tickers: Sequence[str],
    *,
    label: str,
    dimension: str,
    signal: str,
    horizons: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    if dimension == ALL_MEAN:
        return []
    html = _rank_ic_html()
    keys = list(horizons) if horizons is not None else list(HORIZON_KEYS)
    present = {str(row.get("horizon")) for row in company_period if row.get("horizon")}
    rows: list[dict[str, Any]] = []
    for horizon in keys:
        if horizon not in present:
            rows.append(
                {
                    "horizon": horizon,
                    "rank_ic_mean": None,
                    "rank_ic_ir": None,
                    "positive_rank_ic_hit_rate": None,
                    "n_periods": 0,
                }
            )
            continue
        ics = html.period_rank_ics_for_selection(
            company_period,
            list(tickers),
            label_key=label,
            horizon=horizon,
            dimension=dimension,
            signal=signal,
        )
        stats = html.summarize_period_rank_ics(ics)
        rows.append({"horizon": horizon, **stats})
    return rows


def flag_dominant_members(
    members: list[dict[str, Any]],
    *,
    z_key: str = "z_pit",
    abs_floor: float = 1.5,
    gap: float = 1.5,
) -> list[dict[str, Any]]:
    """Mark members whose |z| stands well above the rest of the dimension."""
    scored: list[tuple[int, float]] = []
    for i, row in enumerate(members):
        z_abs = _finite(row.get(z_key))
        if z_abs is None:
            continue
        scored.append((i, abs(z_abs)))
    second = 0.0
    if len(scored) >= 2:
        ordered = sorted((mag for _, mag in scored), reverse=True)
        second = ordered[1]
    elif scored:
        second = 0.0
    out: list[dict[str, Any]] = []
    for i, row in enumerate(members):
        item = dict(row)
        mag = next((m for idx, m in scored if idx == i), None)
        item["dominant"] = bool(
            mag is not None
            and mag >= abs_floor
            and (len(scored) == 1 or mag - second >= gap or (second > 0 and mag >= 2 * second))
        )
        out.append(item)
    return out


def dimension_z_by_ticker(
    panel_rows: Sequence[dict[str, Any]] | None,
    company_period: Sequence[dict[str, Any]] | None,
    *,
    fiscal_period: str,
    dimension: str,
    tickers: Sequence[str],
    quant_signal: str = "quant_z_pit",
) -> dict[str, float]:
    """Dimension z for one selected fiscal period.

    Prefer history-panel z on ``fiscal_period`` + dimension. Fall back to
    company_period only when ``period`` or ``fiscal_period`` equals that
    label exactly. Never invent a FY↔calendar-Q mapping — those often
    disagree, and last-write-wins across periods is worse.
    """
    want = {str(ticker).strip().upper() for ticker in tickers if str(ticker).strip()}
    selected = str(fiscal_period or "").strip()
    out: dict[str, float] = {}
    if not selected or not want:
        return out

    panel_key = (
        "quant_guidance_revision_z_pit"
        if quant_signal == "quant_guidance_revision_z_pit"
        else "quant_z_pit"
    )
    for row in panel_rows or []:
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker not in want or ticker in out:
            continue
        if str(row.get("dimension") or "") != dimension:
            continue
        if str(row.get("fiscal_period") or "").strip() != selected:
            continue
        z_val = _finite(row.get(panel_key))
        if z_val is not None:
            out[ticker] = z_val

    if len(out) == len(want):
        return out

    for row in company_period or []:
        ticker = str(row.get("ticker") or "").strip().upper()
        if ticker not in want or ticker in out:
            continue
        if str(row.get("dimension") or "") != dimension:
            continue
        if str(row.get("signal") or "") != quant_signal:
            continue
        row_period = str(row.get("period") or "").strip()
        row_fiscal = str(row.get("fiscal_period") or "").strip()
        if selected not in {row_period, row_fiscal}:
            continue
        z_val = _finite(row.get("signal_mean"))
        if z_val is not None:
            out[ticker] = z_val
    return out


def revision_z_lookup(panel_rows: Sequence[dict[str, Any]]) -> dict[tuple[str, str], float]:
    """Map (ticker, fiscal_period or calendar quarter) → T+7 revision z."""
    out: dict[tuple[str, str], float] = {}
    for row in panel_rows:
        ticker = str(row.get("ticker") or "").strip().upper()
        z_val = _finite(row.get("quant_guidance_revision_z_pit"))
        if not ticker or z_val is None:
            continue
        fiscal = str(row.get("fiscal_period") or "").strip()
        calendar = str(row.get("period_end_calendar_quarter") or "").strip()
        if fiscal:
            out[(ticker, fiscal)] = z_val
        if calendar:
            out[(ticker, calendar)] = z_val
    return out


def join_street_overlay(
    company_period: list[dict[str, Any]],
    panel_rows: Sequence[dict[str, Any]] | None,
    *,
    label: str,
    horizon: str,
    dimension: str,
    signal: str,
    tickers: Sequence[str],
    period: str,
) -> dict[str, Any]:
    """Call-time signal vs T+7 street revision vs forward return.

    ``period`` is required. Pooling names across quarters into one Spearman
    is the same unit-of-observation bug we already block for ``ALL_MEAN``.
    """
    spearman = _spearman()
    lookup = revision_z_lookup(panel_rows or [])
    want = {str(t).upper() for t in tickers}
    signal_rows = filter_rank_ic_rows(
        company_period,
        label_key=label,
        horizon=horizon,
        dimension=dimension,
        signal=signal,
        period=period,
        tickers=list(want),
    )
    revision_rows = filter_rank_ic_rows(
        company_period,
        label_key=label,
        horizon=horizon,
        dimension=dimension,
        signal="quant_guidance_revision_z_pit",
        period=period,
        tickers=list(want),
    )
    for row in revision_rows:
        ticker = str(row.get("ticker") or "").upper()
        per = str(row.get("period") or "")
        z_val = _finite(row.get("signal_mean"))
        if ticker and per and z_val is not None:
            lookup.setdefault((ticker, per), z_val)

    joined: list[dict[str, Any]] = []
    for row in signal_rows:
        ticker = str(row.get("ticker") or "").upper()
        per = str(row.get("period") or "")
        if ticker not in want:
            continue
        sig = _finite(row.get("signal_mean"))
        ret = _finite(row.get("label_mean"))
        if sig is None or ret is None:
            continue
        rev = lookup.get((ticker, per))
        joined.append(
            {
                "ticker": ticker,
                "period": per,
                "signal_mean": sig,
                "revision_z": rev,
                "label_mean": ret,
            }
        )

    xs = [r["signal_mean"] for r in joined]
    ys = [r["label_mean"] for r in joined]
    rev_pairs = [
        (r["revision_z"], r["label_mean"])
        for r in joined
        if r.get("revision_z") is not None
    ]
    missing = not joined or all(r.get("revision_z") is None for r in joined)
    return {
        "rows": joined,
        "signal_rank_ic": spearman(xs, ys) if joined else None,
        "revision_rank_ic": spearman(
            [p[0] for p in rev_pairs],
            [p[1] for p in rev_pairs],
        )
        if len(rev_pairs) >= MIN_CROSS_SECTION
        else None,
        "missing_revision": missing,
        "n": len(joined),
        "n_revision": len(rev_pairs),
    }


def latest_period_with_n(
    company_period: list[dict[str, Any]],
    tickers: Sequence[str],
    *,
    label: str,
    horizon: str,
    dimension: str,
    signal: str,
    min_n: int = MIN_CROSS_SECTION,
) -> str | None:
    periods = periods_for_cell(
        company_period, label=label, horizon=horizon, dimension=dimension, signal=signal
    )
    want = {str(t).upper() for t in tickers}
    for period in reversed(periods):
        n = sum(
            1
            for row in company_period
            if str(row.get("label_key")) == label
            and str(row.get("horizon")) == horizon
            and str(row.get("dimension")) == dimension
            and str(row.get("signal")) == signal
            and str(row.get("period")) == period
            and str(row.get("ticker") or "").upper() in want
            and _finite(row.get("signal_mean")) is not None
            and _finite(row.get("label_mean")) is not None
        )
        if n >= min_n:
            return period
    return periods[-1] if periods else None


def _default_dimension(bundle: RankIcBundle) -> str:
    dims = real_dimensions(bundle.leaderboard or bundle.company_period or bundle.period_ic)
    if "capital_allocation" in dims:
        return "capital_allocation"
    return dims[0] if dims else "demand"


def _default_signal(bundle: RankIcBundle, *, label: str, horizon: str) -> str:
    for row in bundle.leaderboard:
        if str(row.get("label") or row.get("label_key")) != label:
            continue
        if str(row.get("horizon")) != horizon:
            continue
        if _finite(row.get("rank_ic_mean")) is None:
            continue
        sig = str(row.get("signal") or "")
        if sig:
            return sig
    signals = unique_sorted(bundle.leaderboard or bundle.company_period, "signal")
    if "llm_level" in signals:
        return "llm_level"
    return signals[0] if signals else "llm_level"


def render_rank_ic_filters(
    st: Any,
    bundle: RankIcBundle,
    *,
    universe: Sequence[str],
    available_tickers: Sequence[str],
) -> RankIcFilters:
    labels = unique_sorted(bundle.leaderboard, "label")
    if not labels:
        labels = unique_sorted(bundle.company_period, "label_key")
    if not labels:
        labels = [DEFAULT_LABEL]
    horizons = unique_sorted(
        bundle.leaderboard or bundle.company_period or bundle.period_ic,
        "horizon",
        order=HORIZON_KEYS,
    )
    if not horizons:
        horizons = list(HORIZON_KEYS)
    dims = unique_sorted(bundle.leaderboard or bundle.company_period, "dimension")
    if not dims:
        dims = [_default_dimension(bundle), ALL_MEAN]
    signals = unique_sorted(bundle.leaderboard or bundle.company_period, "signal")
    if not signals:
        signals = ["llm_level"]

    label_index = labels.index(DEFAULT_LABEL) if DEFAULT_LABEL in labels else 0
    horizon_index = horizons.index(DEFAULT_HORIZON) if DEFAULT_HORIZON in horizons else 0
    default_dim = _default_dimension(bundle)
    dim_index = dims.index(default_dim) if default_dim in dims else 0

    c1, c2, c3, c4 = st.columns(4)
    label = c1.selectbox(
        "Label",
        labels,
        index=label_index,
        format_func=label_display,
        key="rank_ic_label",
    )
    horizon = c2.selectbox(
        "Horizon",
        horizons,
        index=horizon_index,
        key="rank_ic_horizon",
    )
    dimension = c3.selectbox(
        "Dimension",
        dims,
        index=dim_index,
        format_func=dimension_label,
        key="rank_ic_dimension",
    )
    default_sig = _default_signal(bundle, label=str(label), horizon=str(horizon))
    sig_index = signals.index(default_sig) if default_sig in signals else 0
    signal = c4.selectbox(
        "Signal",
        signals,
        index=sig_index,
        format_func=signal_label,
        key="rank_ic_signal",
    )
    return RankIcFilters(
        label=str(label),
        horizon=str(horizon),
        dimension=str(dimension),
        signal=str(signal),
        universe=list(universe),
        full_universe=is_full_universe(universe, available_tickers),
    )


def render_workbench_radio(st: Any) -> str:
    options = [f"Explore · {name}" for name in EXPLORE_ORDER] + [
        f"Explain · {name}" for name in EXPLAIN_ORDER
    ]
    choice = st.sidebar.radio("Workbench", options, key="rank_ic_view")
    return str(choice).split(" · ", 1)[-1]


def _need_company_period(st: Any, bundle: RankIcBundle, *, subset: bool) -> bool:
    if bundle.company_period:
        return False
    if subset:
        st.warning(
            "Subset Rank IC needs `narrative_signal_eval_company_period.csv`. "
            "Run evaluate_narrative_signals.py, or "
            "`python scripts/_rebuild_rank_ic_html.py` to extract it from the HTML report."
        )
        return True
    return False


def _heatmap_figure(rows: list[dict[str, Any]], periods: list[str], signals: list[str]) -> Any:
    import plotly.graph_objects as go  # type: ignore

    by_key = {(str(r.get("signal")), str(r.get("period"))): _finite(r.get("rank_ic")) for r in rows}
    z = [[by_key.get((sig, period)) for period in periods] for sig in signals]
    return go.Figure(
        data=go.Heatmap(
            z=z,
            x=periods,
            y=[signal_label(s) for s in signals],
            colorscale="RdBu",
            zmid=0,
            colorbar={"title": "Rank IC"},
            hovertemplate="signal=%{y}<br>period=%{x}<br>Rank IC=%{z:.3f}<extra></extra>",
        )
    ).update_layout(
        title="Period × signal Rank IC",
        xaxis_title="Period",
        yaxis_title="Signal",
        height=max(280, 40 * len(signals) + 120),
        margin={"l": 120, "r": 40, "t": 40, "b": 80},
    )


def render_period_heatmap(
    st: Any,
    data: DashboardData,
    bundle: RankIcBundle,
    filters: RankIcFilters,
) -> None:
    del data
    st.subheader("Period heatmap")
    st.caption("Walk-forward Rank IC by period (columns) and signal (rows) for the active dimension.")
    if filters.dimension == ALL_MEAN:
        st.warning(all_mean_blocked_message())
        return
    signals = unique_sorted(bundle.leaderboard or bundle.company_period, "signal")
    subset = not filters.full_universe
    if (subset or not bundle.period_ic) and bundle.company_period:
        if subset and _need_company_period(st, bundle, subset=True):
            return
        periods = periods_for_cell(
            bundle.company_period,
            label=filters.label,
            horizon=filters.horizon,
            dimension=filters.dimension,
        )
        rows = subset_period_ic_rows(
            bundle.company_period,
            filters.universe,
            label=filters.label,
            horizon=filters.horizon,
            dimension=filters.dimension,
            signals=signals,
            periods=periods,
        )
        if subset:
            st.caption(
                f"Rank IC recomputed for {len(filters.universe)} companies in the active universe."
            )
    else:
        if subset and _need_company_period(st, bundle, subset=True):
            return
        rows = filter_rank_ic_rows(
            bundle.period_ic,
            label_key=filters.label,
            horizon=filters.horizon,
            dimension=filters.dimension,
        )
        periods = _sort_periods(
            unique_sorted(rows, "period") or unique_sorted(rows, "fiscal_period")
        )
        if not rows:
            st.info("No period-IC rows for this cell. Generate Rank IC artifacts first.")
            return
    thin = []
    for row in rows:
        n_val = _finite(row.get("n"))
        if n_val is not None and int(n_val) < MIN_CROSS_SECTION:
            thin.append(row)
    if thin:
        st.caption(
            f"{len(thin)} cells have n < {MIN_CROSS_SECTION} (Spearman undefined / dropped)."
        )
    if not periods or not signals:
        st.info("Nothing to plot for this selection.")
        return
    _plotly_chart(st, _heatmap_figure(rows, periods, signals), key="rank_ic_heatmap")


def render_company_quarter(
    st: Any,
    data: DashboardData,
    bundle: RankIcBundle,
    filters: RankIcFilters,
) -> None:
    del data
    st.subheader("Company × quarter")
    st.caption("Company signal in each period; small r is forward specific return. Footer is that quarter’s Rank IC.")
    if filters.dimension == ALL_MEAN:
        st.warning(all_mean_blocked_message())
        return
    if _need_company_period(st, bundle, subset=True):
        return
    if not bundle.company_period:
        st.info(
            "Company × quarter needs `narrative_signal_eval_company_period.csv`. "
            "Run evaluate_narrative_signals.py or scripts/_rebuild_rank_ic_html.py."
        )
        return
    periods = periods_for_cell(
        bundle.company_period,
        label=filters.label,
        horizon=filters.horizon,
        dimension=filters.dimension,
        signal=filters.signal,
    )
    rows = filter_rank_ic_rows(
        bundle.company_period,
        label_key=filters.label,
        horizon=filters.horizon,
        dimension=filters.dimension,
        signal=filters.signal,
        tickers=filters.universe,
    )
    by_key = {
        (str(r.get("ticker")).upper(), str(r.get("period"))): r for r in rows
    }
    display: list[dict[str, Any]] = []
    for ticker in filters.universe:
        item: dict[str, Any] = {"Ticker": format_company_label(ticker)}
        for period in periods:
            cell = by_key.get((ticker, period))
            if not cell:
                item[period] = "—"
                continue
            sig = _fmt(cell.get("signal_mean"), 2)
            ret = _fmt(cell.get("label_mean"), 3)
            item[period] = f"{sig}  r {ret}"
        display.append(item)
    _table(st, display, height=min(560, 48 + 28 * max(len(display), 4)))
    pic = subset_period_ic_rows(
        bundle.company_period,
        filters.universe,
        label=filters.label,
        horizon=filters.horizon,
        dimension=filters.dimension,
        signals=[filters.signal],
        periods=periods,
    )
    footer = {"Ticker": "Period Rank IC"}
    pic_map = {str(r.get("period")): r for r in pic}
    for period in periods:
        footer[period] = _fmt(pic_map.get(period, {}).get("rank_ic"))
    st.caption("Period Rank IC (footer)")
    _table(st, [footer])


def render_leaderboard(
    st: Any,
    data: DashboardData,
    bundle: RankIcBundle,
    filters: RankIcFilters,
) -> None:
    del data
    st.subheader("Leaderboard")
    st.caption("Walk-forward mean Rank IC / IR / hit rate for the active label, horizon, and dimension.")
    signals = unique_sorted(bundle.leaderboard or bundle.company_period, "signal")
    if filters.full_universe:
        rows = filter_rank_ic_rows(
            bundle.leaderboard,
            label=filters.label,
            horizon=filters.horizon,
            dimension=filters.dimension,
        )
        source = "full book"
    else:
        if _need_company_period(st, bundle, subset=True):
            return
        rows = subset_leaderboard_rows(
            bundle.company_period,
            filters.universe,
            label=filters.label,
            horizon=filters.horizon,
            dimension=filters.dimension,
            signals=signals,
        )
        source = f"recomputed on {len(filters.universe)} companies"
    st.caption(f"Source: {source}.")
    display = [
        {
            "Signal": signal_label(str(r.get("signal"))),
            "Rank IC mean": _finite(r.get("rank_ic_mean")),
            "IR": _finite(r.get("rank_ic_ir")),
            "Hit rate": _finite(r.get("positive_rank_ic_hit_rate")),
            "Periods": r.get("n_periods"),
            "Rows": r.get("n_rows"),
        }
        for r in rows
    ]
    _table(st, display)


def render_by_dimension(
    st: Any,
    data: DashboardData,
    bundle: RankIcBundle,
    filters: RankIcFilters,
) -> None:
    del data
    st.subheader("By dimension")
    st.caption("Production matrix: each cell is that signal × dimension walk-forward Rank IC mean.")
    signals = unique_sorted(bundle.leaderboard or bundle.company_period, "signal")
    dims = real_dimensions(bundle.leaderboard or bundle.company_period)
    if filters.full_universe:
        raw = filter_rank_ic_rows(
            bundle.leaderboard,
            label=filters.label,
            horizon=filters.horizon,
        )
        source = "full book"
    else:
        if _need_company_period(st, bundle, subset=True):
            return
        raw = subset_dimension_matrix(
            bundle.company_period,
            filters.universe,
            label=filters.label,
            horizon=filters.horizon,
            dimensions=dims,
            signals=signals,
        )
        source = f"recomputed on {len(filters.universe)} companies"
    st.caption(f"Source: {source}.")
    by_key = {
        (str(r.get("dimension")), str(r.get("signal"))): _finite(r.get("rank_ic_mean"))
        for r in raw
    }
    display: list[dict[str, Any]] = []
    for dim in dims:
        item: dict[str, Any] = {"Dimension": dimension_label(dim)}
        for sig in signals:
            item[signal_label(sig)] = by_key.get((dim, sig))
        display.append(item)
    mean_row: dict[str, Any] = {"Dimension": "All dims (mean)"}
    for sig in signals:
        vals = [by_key.get((dim, sig)) for dim in dims]
        nums = [v for v in vals if v is not None]
        mean_row[signal_label(sig)] = (sum(nums) / len(nums)) if nums else None
    display.append(mean_row)
    _table(st, display)


def render_agreement(
    st: Any,
    data: DashboardData,
    bundle: RankIcBundle,
    filters: RankIcFilters,
) -> None:
    del data
    st.subheader("Agreement effect")
    st.caption(
        "agrees_with_quant vs forward specific return. Book-level artifact — "
        "not recomputed for a sector/custom subset (same honesty as the HTML report)."
    )
    if not filters.full_universe:
        st.info(
            "Agreement effect is the full-book bootstrap. Narrowing the company "
            "filter does not recompute these spreads."
        )
    rows = filter_rank_ic_rows(
        bundle.agreement,
        label_key=filters.label,
        horizon=filters.horizon,
    )
    if not rows:
        st.info("No agreement-effect rows for this label/horizon. Regen Rank IC with agreement enabled.")
        return
    display = [
        {
            "Dimension": (
                "All quant dims (pooled)"
                if str(r.get("dimension")) in {"pooled", "", "nan", "None"}
                else dimension_label(str(r.get("dimension")))
            ),
            "n agree": r.get("n_agree"),
            "n disagree": r.get("n_disagree"),
            "Mean return (agree)": _finite(r.get("mean_return_agree")),
            "Mean return (disagree)": _finite(r.get("mean_return_disagree")),
            "Spread": _finite(r.get("spread")),
            "CI low": _finite(r.get("ci_low")),
            "CI high": _finite(r.get("ci_high")),
            "# tickers": r.get("n_tickers"),
        }
        for r in rows
    ]
    _table(st, display)


def render_jackknife(
    st: Any,
    data: DashboardData,
    bundle: RankIcBundle,
    filters: RankIcFilters,
) -> None:
    del data
    st.subheader("Jackknife")
    if filters.dimension == ALL_MEAN:
        st.warning(all_mean_blocked_message())
        return
    default_mode = "Selection robustness" if not filters.full_universe else "Book influence"
    mode = st.radio(
        "Mode",
        ("Book influence", "Selection robustness"),
        index=0 if default_mode == "Book influence" else 1,
        horizontal=True,
        key="rank_ic_jk_mode",
    )
    html = _rank_ic_html()
    if mode == "Book influence":
        st.caption(
            "Leave-one-ticker-out on the **full book**. Values are influence on book Rank IC, "
            "not peer-set IC. Switch to Selection robustness to recompute LOO on the current list."
        )
        artifact = [
            r
            for r in bundle.jackknife
            if str(r.get("signal")) == filters.signal
            and str(r.get("dimension")) == filters.dimension
            and str(r.get("label_key") or r.get("label") or "") == filters.label
            and str(r.get("horizon") or "") == filters.horizon
        ]
        if not artifact:
            st.warning(
                "Book influence leave-one-out is missing from this artifact "
                "(dashboard fast regen skips `--jackknife`). Run a full Rank IC regen "
                "with jackknife enabled. Selection robustness still works from "
                "company_period when the filter has at least three companies."
            )
            return
        want = {t.upper() for t in filters.universe}
        shown = [r for r in artifact if str(r.get("held_out_ticker") or "").upper() in want]
        baseline_rows = filter_rank_ic_rows(
            bundle.period_ic,
            label_key=filters.label,
            horizon=filters.horizon,
            dimension=filters.dimension,
            signal=filters.signal,
        )
        base_mean = html.summarize_period_rank_ics(
            [_finite(r.get("rank_ic")) for r in baseline_rows]
        ).get("rank_ic_mean")
        if not filters.full_universe:
            st.info(
                "Showing held-out rows for selected tickers only; deltas are vs full-book baseline."
            )
        display = []
        for row in shown:
            mean = _finite(row.get("rank_ic_mean"))
            delta = (mean - base_mean) if mean is not None and base_mean is not None else None
            display.append(
                {
                    "Held out": row.get("held_out_ticker"),
                    "Rank IC mean": mean,
                    "IR": _finite(row.get("rank_ic_ir")),
                    "Pooled Rank IC": _finite(row.get("pooled_rank_ic")),
                    "Periods": row.get("n_periods"),
                    "Rows": row.get("n_rows"),
                    "Δ vs baseline": delta,
                }
            )
        st.caption(f"Baseline Rank IC mean {_fmt(base_mean)}")
        _table(st, display)
        return

    st.caption(
        "Leave-one-ticker-out Rank IC on the **current universe**. "
        "Δ = IC(U without t) − IC(U)."
    )
    if _need_company_period(st, bundle, subset=True):
        return
    if len(filters.universe) < MIN_CROSS_SECTION:
        st.warning(
            f"Selection robustness needs at least {MIN_CROSS_SECTION} companies in the filter."
        )
        return
    summary = html.selection_jackknife_summary(
        bundle.company_period,
        filters.universe,
        label_key=filters.label,
        horizon=filters.horizon,
        dimension=filters.dimension,
        signal=filters.signal,
    )
    if summary.get("too_small"):
        st.warning("Universe too small for selection jackknife.")
        return
    baseline = summary.get("baseline") or {}
    st.caption(
        f"Selection baseline Rank IC mean {_fmt(baseline.get('rank_ic_mean'))} · "
        f"IR {_fmt(baseline.get('rank_ic_ir'))} · n_periods {baseline.get('n_periods')}"
    )
    display = [
        {
            "Held out": r.get("held_out_ticker"),
            "Rank IC mean": _finite(r.get("rank_ic_mean")),
            "IR": _finite(r.get("rank_ic_ir")),
            "Periods": r.get("n_periods"),
            "Δ vs baseline": _finite(r.get("delta")),
        }
        for r in (summary.get("rows") or [])
    ]
    _table(st, display)


def render_quarter_drivers(
    st: Any,
    data: DashboardData,
    bundle: RankIcBundle,
    filters: RankIcFilters,
) -> None:
    del data
    st.subheader("Quarter drivers")
    st.caption(
        "This quarter’s autopsy — who made this period’s Rank IC — not book jackknife."
    )
    if filters.dimension == ALL_MEAN:
        st.warning(all_mean_blocked_message())
        return
    if _need_company_period(st, bundle, subset=True):
        return
    if not bundle.company_period:
        st.info("Quarter drivers need company_period rows.")
        return
    periods = periods_for_cell(
        bundle.company_period,
        label=filters.label,
        horizon=filters.horizon,
        dimension=filters.dimension,
        signal=filters.signal,
    )
    default = latest_period_with_n(
        bundle.company_period,
        filters.universe,
        label=filters.label,
        horizon=filters.horizon,
        dimension=filters.dimension,
        signal=filters.signal,
    )
    if not periods:
        st.info("No periods for this cell.")
        return
    index = periods.index(default) if default in periods else len(periods) - 1
    period = st.selectbox("Period", periods, index=index, key="rank_ic_driver_period")
    raw = filter_rank_ic_rows(
        bundle.company_period,
        label_key=filters.label,
        horizon=filters.horizon,
        dimension=filters.dimension,
        signal=filters.signal,
        period=str(period),
        tickers=filters.universe,
    )
    drivers = period_leave_one_out(raw)
    if len(drivers) < MIN_CROSS_SECTION:
        st.warning(
            f"Need at least {MIN_CROSS_SECTION} names with signal and return in {period}."
        )
        return
    import plotly.graph_objects as go  # type: ignore

    fig = go.Figure(
        data=go.Scatter(
            x=[r["signal_mean"] for r in drivers],
            y=[r["label_mean"] for r in drivers],
            mode="markers+text",
            text=[r["ticker"] for r in drivers],
            textposition="top center",
            hovertemplate=(
                "%{text}<br>signal=%{x:.3f}<br>return=%{y:.4f}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        xaxis_title=signal_label(filters.signal),
        yaxis_title="Forward specific return",
        height=420,
        title=f"{period} · baseline Rank IC {_fmt(drivers[0].get('baseline_rank_ic'))}",
    )
    _plotly_chart(st, fig, key="rank_ic_drivers_scatter")
    _table(
        st,
        [
            {
                "Ticker": format_company_label(r["ticker"]),
                "Signal": r["signal_mean"],
                "Return": r["label_mean"],
                "Signal rank": r["signal_rank"],
                "Return rank": r["return_rank"],
                "LOO Rank IC": r["loo_rank_ic"],
                "Δ Rank IC": r["loo_delta"],
            }
            for r in drivers
        ],
    )


def render_measure_drilldown(
    st: Any,
    data: DashboardData,
    bundle: RankIcBundle,
    filters: RankIcFilters,
) -> None:
    st.subheader("Measure drill-down")
    st.caption(
        "Member measures behind the active dimension’s quant stack. "
        "Highlighted when one member dominates the dimension z."
    )
    if filters.dimension == ALL_MEAN:
        st.warning("Pick a real dimension to see member measures.")
        return
    if not bundle.measure_members:
        st.info(
            "Measure members CSV not found. Run evaluate_narrative_signals.py "
            "(writes narrative_signal_eval_measure_members.csv from the z-scored spine)."
        )
        return
    members = [
        r
        for r in bundle.measure_members
        if str(r.get("dimension")) == filters.dimension
        and str(r.get("ticker") or "").upper() in {t.upper() for t in filters.universe}
    ]
    if not members:
        st.info("No member-measure rows for this dimension and universe.")
        return
    if filters.signal not in {"quant_z_pit", "quant_guidance_revision_z_pit"}:
        st.caption(
            f"Active signal is {signal_label(filters.signal)} (not quant-derived). "
            "Members below are what the quant stack did that quarter; narrative sits in the header filters."
        )
    periods = unique_sorted(members, "period") or unique_sorted(members, "fiscal_period")
    if not periods:
        st.info("Member rows have no fiscal period to slice on.")
        return
    period = st.selectbox(
        "Period (fiscal)",
        _sort_periods(periods, period_col="fiscal_period"),
        index=len(periods) - 1 if periods else 0,
        key="rank_ic_measure_period",
    )
    slice_rows = [
        r
        for r in members
        if str(r.get("period") or r.get("fiscal_period")) == str(period)
    ]
    quant_signal = (
        "quant_guidance_revision_z_pit"
        if filters.dimension == "guidance"
        else "quant_z_pit"
    )
    dim_z_by_ticker = dimension_z_by_ticker(
        data.rows,
        bundle.company_period,
        fiscal_period=str(period),
        dimension=filters.dimension,
        tickers=filters.universe,
        quant_signal=quant_signal,
    )

    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in slice_rows:
        grouped.setdefault(str(row.get("ticker")).upper(), []).append(row)
    display: list[dict[str, Any]] = []
    for ticker, group in sorted(grouped.items()):
        flagged = flag_dominant_members(group)
        for row in flagged:
            display.append(
                {
                    "Ticker": format_company_label(ticker),
                    "Measure": row.get("measure_name") or row.get("measure"),
                    "Code": row.get("measure"),
                    "Surprise %": _finite(row.get("surprise_pct")),
                    "z PIT": _finite(row.get("z_pit")),
                    "z full-sample": _finite(row.get("z_fullsample")),
                    "Dimension z": dim_z_by_ticker.get(ticker),
                    "Dominant": "yes" if row.get("dominant") else "",
                }
            )
    _table(st, display)


def render_horizon_fingerprint(
    st: Any,
    data: DashboardData,
    bundle: RankIcBundle,
    filters: RankIcFilters,
) -> None:
    del data
    st.subheader("Horizon fingerprint")
    st.caption(
        "Same signal × dimension × universe across all five forward-return clocks. "
        "Reversals show up here without flipping the horizon control."
    )
    if filters.dimension == ALL_MEAN:
        st.warning(all_mean_blocked_message())
        return
    if _need_company_period(st, bundle, subset=True):
        return
    if not bundle.company_period:
        st.info("Horizon fingerprint needs company_period rows.")
        return
    rows = horizon_fingerprint(
        bundle.company_period,
        filters.universe,
        label=filters.label,
        dimension=filters.dimension,
        signal=filters.signal,
    )
    display = [
        {
            "Horizon": r["horizon"],
            "Rank IC mean": _finite(r.get("rank_ic_mean")),
            "IR": _finite(r.get("rank_ic_ir")),
            "Hit rate": _finite(r.get("positive_rank_ic_hit_rate")),
            "n periods": r.get("n_periods"),
        }
        for r in rows
    ]
    _table(st, display)
    import plotly.graph_objects as go  # type: ignore

    fig = go.Figure(
        data=go.Heatmap(
            z=[[_finite(r.get("rank_ic_mean")) for r in rows]],
            x=[r["horizon"] for r in rows],
            y=["Rank IC mean"],
            colorscale="RdBu",
            zmid=0,
            colorbar={"title": "Rank IC"},
        )
    )
    fig.update_layout(height=180, margin={"l": 80, "r": 40, "t": 20, "b": 40})
    _plotly_chart(st, fig, key="rank_ic_horizon_fp")


def render_street_overlay(
    st: Any,
    data: DashboardData,
    bundle: RankIcBundle,
    filters: RankIcFilters,
) -> None:
    st.subheader("Street overlay")
    st.caption(
        "Three clocks on the same names: call-time signal, T+7 analyst revision "
        "(`quant_guidance_revision_z_pit`), and forward specific return over the "
        "selected Rank IC horizon — not the 1-minute tape."
    )
    if filters.dimension == ALL_MEAN:
        st.warning(all_mean_blocked_message())
        return
    if filters.dimension == "guidance":
        st.info(
            "Guidance’s quant is revision-based by construction. The revision clock "
            "here is the same family as the guidance quant — don’t read it as an "
            "independent street overlay."
        )
    if _need_company_period(st, bundle, subset=True):
        return
    if not bundle.company_period:
        st.info("Street overlay needs company_period rows.")
        return
    periods = periods_for_cell(
        bundle.company_period,
        label=filters.label,
        horizon=filters.horizon,
        dimension=filters.dimension,
        signal=filters.signal,
    )
    if not periods:
        st.info("No periods in this cell for a street overlay.")
        return
    default = latest_period_with_n(
        bundle.company_period,
        filters.universe,
        label=filters.label,
        horizon=filters.horizon,
        dimension=filters.dimension,
        signal=filters.signal,
    )
    index = periods.index(default) if default in periods else len(periods) - 1
    period_choice = st.selectbox("Period", periods, index=index, key="rank_ic_street_period")
    overlay = join_street_overlay(
        bundle.company_period,
        data.rows,
        label=filters.label,
        horizon=filters.horizon,
        dimension=filters.dimension,
        signal=filters.signal,
        tickers=filters.universe,
        period=str(period_choice),
    )
    if overlay["missing_revision"]:
        st.info(
            "No T+7 `quant_guidance_revision_z_pit` on the history panel or company_period "
            "for this cell. Street overlay is empty until that column is present."
        )
        return
    left, right = st.columns(2)
    left.metric("Call-time Rank IC", _fmt(overlay.get("signal_rank_ic")))
    right.metric("Revision Rank IC", _fmt(overlay.get("revision_rank_ic")))
    st.caption(
        "Revision Rank IC is Spearman of T+7 street revision vs the same forward return. "
        "When it matches call-time Rank IC, the street already knew."
    )
    import plotly.graph_objects as go  # type: ignore

    rows = overlay["rows"]
    fig = go.Figure(
        data=go.Scatter(
            x=[r["signal_mean"] for r in rows],
            y=[r["label_mean"] for r in rows],
            mode="markers+text",
            text=[r["ticker"] for r in rows],
            textposition="top center",
            marker={
                "size": 10,
                "color": [r["revision_z"] if r["revision_z"] is not None else 0 for r in rows],
                "colorscale": "RdBu",
                "cmid": 0,
                "colorbar": {"title": "T+7 rev z"},
            },
            hovertemplate=(
                "%{text}<br>signal=%{x:.3f}<br>return=%{y:.4f}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        xaxis_title=f"Call-time {signal_label(filters.signal)}",
        yaxis_title="Forward specific return",
        height=420,
    )
    _plotly_chart(st, fig, key="rank_ic_street_scatter")
    ranked = sorted(rows, key=lambda r: r["signal_mean"], reverse=True)
    _table(
        st,
        [
            {
                "Ticker": format_company_label(r["ticker"]),
                "Period": r["period"],
                "Call signal": r["signal_mean"],
                "T+7 revision z": r["revision_z"],
                "Forward return": r["label_mean"],
            }
            for r in ranked
        ],
    )


RANK_IC_VIEWS = {
    "Period heatmap": render_period_heatmap,
    "Company × quarter": render_company_quarter,
    "Leaderboard": render_leaderboard,
    "By dimension": render_by_dimension,
    "Agreement effect": render_agreement,
    "Jackknife": render_jackknife,
    "Quarter drivers": render_quarter_drivers,
    "Measure drill-down": render_measure_drilldown,
    "Horizon fingerprint": render_horizon_fingerprint,
    "Street overlay": render_street_overlay,
}


def render_rank_ic_workbench(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    del sector_choice
    universe = _universe(data, sector_tickers)
    bundle = load_rank_ic_bundle()
    st.caption(
        "Production signal pack, read-only. Slice and explain Rank IC here. "
        "Rank IC Lab is the what-if sandbox for weights and saved recipes."
    )
    if not bundle.available:
        st.info(bundle.empty_message)
        if bundle.missing:
            st.caption("Missing: " + ", ".join(bundle.missing[:4]))
        return
    generated = bundle.meta.get("generated_at")
    if generated:
        st.caption(f"Artifacts generated {generated}")
    filters = render_rank_ic_filters(
        st,
        bundle,
        universe=universe,
        available_tickers=data.tickers,
    )
    st.caption("Label, horizon, and dimension are shared with Rank IC Lab.")
    st.caption(
        f"{label_display(filters.label)} · {filters.horizon} · "
        f"{dimension_label(filters.dimension)} · {signal_label(filters.signal)} · "
        f"{len(filters.universe)} companies"
    )
    view_name = render_workbench_radio(st)
    renderer = RANK_IC_VIEWS.get(view_name)
    if renderer is None:
        st.error(f"Unknown workbench view: {view_name}")
        return
    renderer(st, data, bundle, filters)
