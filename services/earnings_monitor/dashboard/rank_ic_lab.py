"""Rank IC Lab: what-if sandbox for signal weights and sector recipes.

Production pack stays frozen. This page never writes ``config/signal_packs/``.
Co-pilot / promotion / prompt rescoring are out of scope for v1.
"""
from __future__ import annotations

import os
from typing import Any, Mapping, Sequence

from .data import DashboardData
from .lab_store import (
    LabStoreError,
    append_trial,
    default_lab_store_path,
    get_recipe,
    load_lab_store,
    recipes_for,
    save_lab_store,
    trials_for,
    universe_key,
    upsert_recipe,
)
from .rank_ic_research import (
    ALL_MEAN,
    DEFAULT_HORIZON,
    DEFAULT_LABEL,
    HORIZON_KEYS,
    all_mean_blocked_message,
    dimension_label,
    label_display,
    periods_for_cell,
    real_dimensions,
    signal_label,
)
from .research_data import (
    RankIcBundle,
    import_sn,
    load_rank_ic_bundle,
    resolve_cross_company_root,
    unique_sorted,
)
from .sectors import is_full_universe

LAB_BLEND_SIGNAL = "lab_blend"
CALL_DATE_SIGNALS: tuple[str, ...] = (
    "llm_level",
    "change_magnitude",
    "surprise_magnitude",
    "narrative_novelty",
    "quant_z_pit",
    "agrees_with_quant",
)
REVISION_SIGNAL = "quant_guidance_revision_z_pit"
DEFAULT_BASELINE_SIGNAL = "quant_z_pit"
DEFAULT_MIN_PERIODS = 4
_WEIGHT_EPS = 1e-12
_PENDING_RECIPE_KEY = "lab_pending_recipe"
_PENDING_RESET_KEY = "lab_pending_reset"
_PATH_ID_STAMP = "2026-08-17T17:28:40+00:00"
_PATH_ID_FILENAME = "path_id_v1.json"
_DESK_FILENAME = "desk_path_id_v1.json"
_CLAIMS_FILENAME = "desk_claims_v1.json"


def load_path_id_v1(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Read the adjudicated Path ID artifact. Refuse a mismatched stamp."""
    import json
    from pathlib import Path

    root = resolve_cross_company_root(history_source)
    path = Path(root) / "json" / _PATH_ID_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("generated_at") or "") != _PATH_ID_STAMP:
        return None
    return payload


def load_desk_path_id_v1(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Read the Path ID desk join. Refuse a mismatched stamp."""
    import json
    from pathlib import Path

    root = resolve_cross_company_root(history_source)
    path = Path(root) / "json" / _DESK_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("generated_at") or "") != _PATH_ID_STAMP:
        return None
    return payload


def load_desk_claims_v1(
    history_source: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    """Read the typed claims desk. Refuse a mismatched stamp."""
    import json
    from pathlib import Path

    root = resolve_cross_company_root(history_source)
    path = Path(root) / "json" / _CLAIMS_FILENAME
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(payload, dict):
        return None
    if str(payload.get("generated_at") or "") != _PATH_ID_STAMP:
        return None
    return payload


def desk_row_key(row: Mapping[str, Any]) -> str:
    return f"{row.get('ticker') or ''} {row.get('period') or ''}".strip()


def desk_excerpt_view(
    rows: Sequence[Mapping[str, Any]],
    selected_key: str,
) -> dict[str, Any] | None:
    """One name-quarter excerpt. A 140-row grid is unreadable."""
    want = str(selected_key or "").strip()
    if not want:
        return None
    for row in rows:
        if desk_row_key(row) == want:
            return dict(row)
    return None


def path_id_panel_model(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Pure copy + table for the read-only Lab Path ID panel."""
    passing = [
        name
        for name, ok in (
            ("L1", payload.get("line1")),
            ("L2", payload.get("line2")),
            ("L3", payload.get("line3")),
        )
        if ok
    ]
    passed = bool(payload.get("case_study_pass"))
    if passed:
        caption = "Path ID v1 case study PASS on the locked 17 Aug book."
    else:
        caption = (
            "Path ID v1 case study FAIL. Do not promote a single line."
        )
    if passing:
        caption += " Passing line(s): " + ", ".join(passing) + "."
    return {
        "caption": caption,
        "case_study_pass": passed,
        "generated_at": payload.get("generated_at"),
        "split": payload.get("split"),
        "passing_lines": passing,
        "hit_rate": payload.get("hit_rate"),
        "path_hits": payload.get("path_hits"),
        "path_scored": payload.get("path_scored"),
        "name_paths": list(payload.get("name_paths") or []),
    }


def render_path_id_panel(
    st: Any,
    payload: Mapping[str, Any],
    desk: Mapping[str, Any] | None = None,
) -> None:
    model = path_id_panel_model(payload)
    with st.expander("Path ID v1 — locked 17 Aug book", expanded=False):
        st.caption(model["caption"])
        st.caption(
            f"Stamp {model['generated_at']} · {model['split']} · "
            f"L2 hit rate {model['hit_rate']} "
            f"({model['path_hits']}/{model['path_scored']})"
        )
        rows = model["name_paths"]
        if rows:
            st.dataframe(rows, hide_index=True, use_container_width=True)
        if desk is None:
            return
        desk_rows = list(desk.get("rows") or [])
        coverage = desk.get("coverage") or {}
        st.caption(
            "Desk join "
            f"{coverage.get('joined', 0)} cited / "
            f"{coverage.get('missing_fiscal', 0)} missing fiscal / "
            f"{coverage.get('missing_excerpt', 0)} missing excerpt. "
            "One excerpt at a time."
        )
        options = [desk_row_key(row) for row in desk_rows if desk_row_key(row)]
        if not options:
            return
        choice = st.selectbox(
            "Name-quarter excerpt",
            options,
            key="desk_path_id_v1_pick",
        )
        picked = desk_excerpt_view(desk_rows, str(choice or ""))
        if picked is None:
            return
        source = picked.get("source") or ""
        if source:
            st.caption(source)
        fiscal = picked.get("fiscal_period")
        if fiscal:
            st.caption(
                f"{picked.get('ticker')} calendar {picked.get('period')} → {fiscal}"
            )
        status = str(picked.get("excerpt_status") or "missing")
        if status == "missing" or not str(picked.get("excerpt") or "").strip():
            st.info("No verified excerpt on disk. Do not invent a quote.")
            return
        claim = picked.get("claim")
        if claim:
            st.markdown(f"**{claim}**")
        st.write(picked.get("excerpt"))
        rationale = picked.get("rationale")
        if rationale:
            st.caption(rationale)


def render_claims_desk_panel(st: Any, payload: Mapping[str, Any] | None) -> None:
    """Cite-first working set. State is a follow-up cite, not a Path ID hit."""
    if payload is None:
        return
    rows = list(payload.get("rows") or [])
    if not rows:
        return
    counts = payload.get("counts") or {}
    delivery_counts = payload.get("delivery_counts") or {}
    beats = list(payload.get("beats") or [])
    with st.expander("Claims desk v1 — beats and same-object backfill", expanded=False):
        st.caption(
            "Full quote expanders, company-history backdrop, and deliver rate "
            "live on the Claims Desk page. This table stays compact."
        )
        st.caption(str(payload.get("caption") or ""))
        st.caption(
            f"Stamp {payload.get('generated_at')} · {payload.get('split')} · "
            f"pilot {payload.get('n_pilot', 0)} · backfill {payload.get('n_backfill', 0)} · "
            f"open {counts.get('open', 0)} · kept {counts.get('kept', 0)} · "
            f"slipped {counts.get('slipped', 0)} · "
            f"subject-changed {counts.get('subject-changed', 0)} · "
            f"delivered {delivery_counts.get('delivered', 0)} · "
            f"missed {delivery_counts.get('missed', 0)} · "
            f"unresolved {delivery_counts.get('unresolved', 0)} · "
            f"not-a-promise {delivery_counts.get('not-a-promise', 0)}"
        )
        beat_options = ["All beats"] + [
            f"{beat.get('beat_id')} · {beat.get('n_rows')} rows"
            for beat in beats
        ]
        beat_choice = st.selectbox(
            "Beat",
            beat_options,
            key="desk_claims_v1_beat",
        )
        want_beat = None
        if beat_choice != "All beats":
            want_beat = str(beat_choice).split(" · ", 1)[0]
        visible = [
            row
            for row in rows
            if want_beat is None or str(row.get("beat_id") or "") == want_beat
        ]
        table = [
            {
                "beat": row.get("beat_id"),
                "origin": row.get("origin"),
                "name": f"{row.get('ticker')} {row.get('period')}",
                "type": row.get("claim_type"),
                "state": row.get("state"),
                "delivery": row.get("delivery"),
                "cite": row.get("excerpt"),
                "follow_up": row.get("follow_up_excerpt"),
            }
            for row in visible
        ]
        st.dataframe(table, hide_index=True, use_container_width=True)
        options = [
            f"{row.get('ticker')} {row.get('period')}"
            for row in visible
            if row.get("ticker")
        ]
        choice = st.selectbox(
            "Open claim",
            options,
            key="desk_claims_v1_pick",
        )
        picked = None
        for row in rows:
            if f"{row.get('ticker')} {row.get('period')}" == choice:
                picked = row
                break
        if picked is None:
            return
        st.caption(
            f"{picked.get('beat_id')} · {picked.get('origin')} · "
            f"{picked.get('claim_type')} · {picked.get('state')} · "
            f"delivery {picked.get('delivery')} · "
            f"objects {', '.join(str(item) for item in (picked.get('objects') or []))}"
        )
        if picked.get("delivery_basis"):
            st.caption(str(picked.get("delivery_basis")))
        if picked.get("citation"):
            st.caption(str(picked.get("citation")))
        st.write(picked.get("excerpt"))
        follow = picked.get("follow_up_excerpt")
        if follow:
            st.caption(str(picked.get("follow_up_citation") or ""))
            st.write(follow)
        elif picked.get("state") == "open":
            st.info("Still open. No next-quarter cite on this object.")
        else:
            st.info("No follow-up cite on this object.")


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


def _universe(data: DashboardData, sector_tickers: Sequence[str] | None) -> list[str]:
    if sector_tickers is not None:
        return [str(ticker).upper() for ticker in sector_tickers]
    return list(data.tickers)


def default_weights(*, include_revision: bool = False) -> dict[str, float]:
    """Zeros with ``quant_z_pit=1`` so a recipe is explicit."""
    out = {signal: 0.0 for signal in CALL_DATE_SIGNALS}
    out["quant_z_pit"] = 1.0
    if include_revision:
        out[REVISION_SIGNAL] = 0.0
    return out


def active_weights(
    weights: Mapping[str, float],
    *,
    include_revision: bool = False,
) -> dict[str, float]:
    allowed = set(CALL_DATE_SIGNALS)
    if include_revision:
        allowed.add(REVISION_SIGNAL)
    out: dict[str, float] = {}
    for signal, raw in dict(weights).items():
        if signal not in allowed:
            continue
        value = float(raw or 0.0)
        if abs(value) <= _WEIGHT_EPS:
            continue
        out[str(signal)] = value
    return out


def pivot_company_period(
    rows: Sequence[dict[str, Any]],
    tickers: Sequence[str],
    *,
    label: str,
    horizon: str,
    dimension: str,
    signals: Sequence[str],
) -> Any:
    """Wide ticker×period frame with one column per input signal."""
    import pandas as pd  # type: ignore

    want = {str(t).upper() for t in tickers}
    wanted_signals = {str(s) for s in signals}
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        family = str(row.get("label_key") or row.get("label") or "")
        if family != label:
            continue
        if str(row.get("horizon") or "") != horizon:
            continue
        if str(row.get("dimension") or "") != dimension:
            continue
        ticker = str(row.get("ticker") or "").upper()
        if ticker not in want:
            continue
        period = str(row.get("period") or "")
        if not period:
            continue
        rec = by_key.setdefault(
            (ticker, period),
            {
                "ticker": ticker,
                "period": period,
                "dimension": dimension,
                "label_mean": None,
            },
        )
        signal = str(row.get("signal") or "")
        signal_mean = _finite(row.get("signal_mean"))
        if signal in wanted_signals and signal_mean is not None:
            rec[signal] = signal_mean
        label_mean = _finite(row.get("label_mean"))
        if label_mean is not None:
            rec["label_mean"] = label_mean
    if not by_key:
        return pd.DataFrame(
            columns=["ticker", "period", "dimension", "label_mean", *wanted_signals]
        )
    return pd.DataFrame(list(by_key.values()))


def apply_user_blend(
    wide: Any,
    weights: Mapping[str, float],
    *,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> Any:
    """PIT-standardize inputs, then ``sum(w_s * z_s) / sum(|w_s|)`` with user weights."""
    import numpy as np
    import pandas as pd  # type: ignore

    composite = import_sn("composite_signal")
    if wide is None or getattr(wide, "empty", True):
        return pd.Series(dtype=float)
    active = active_weights(weights, include_revision=True)
    if not active:
        return pd.Series(np.nan, index=wide.index, dtype=float)
    frame = wide
    if "dimension" not in frame.columns:
        frame = frame.copy()
        frame["dimension"] = "_"
    z_cols: dict[str, Any] = {}
    for signal in active:
        if signal not in frame.columns:
            continue
        z_cols[signal] = composite.expanding_standardize(
            frame,
            signal,
            period_col="period",
            dimension_col="dimension",
            min_periods=min_periods,
        )
    numerator = pd.Series(0.0, index=frame.index, dtype=float)
    denominator = pd.Series(0.0, index=frame.index, dtype=float)
    any_contribution = pd.Series(False, index=frame.index)
    for signal, weight in active.items():
        z = z_cols.get(signal)
        if z is None:
            continue
        contributes = z.notna()
        numerator = numerator + float(weight) * z.where(contributes, 0.0)
        denominator = denominator + abs(float(weight)) * contributes.astype(float)
        any_contribution = any_contribution | contributes
    blended = numerator / denominator.replace(0.0, np.nan)
    return blended.where(any_contribution, np.nan)


def blend_company_period(
    company_period: Sequence[dict[str, Any]],
    tickers: Sequence[str],
    *,
    label: str,
    horizon: str,
    dimension: str,
    weights: Mapping[str, float],
    include_revision: bool = False,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> list[dict[str, Any]]:
    """Emit synthetic ``lab_blend`` company_period rows for Rank IC helpers."""
    active = active_weights(weights, include_revision=include_revision)
    if not active:
        return []
    wide = pivot_company_period(
        company_period,
        tickers,
        label=label,
        horizon=horizon,
        dimension=dimension,
        signals=list(active),
    )
    blended = apply_user_blend(wide, active, min_periods=min_periods)
    out: list[dict[str, Any]] = []
    for idx, value in blended.items():
        score = _finite(value)
        if score is None:
            continue
        row = wide.loc[idx]
        label_mean = _finite(row.get("label_mean"))
        if label_mean is None:
            continue
        out.append(
            {
                "label_key": label,
                "horizon": horizon,
                "ticker": str(row.get("ticker") or "").upper(),
                "period": str(row.get("period") or ""),
                "signal": LAB_BLEND_SIGNAL,
                "dimension": dimension,
                "signal_mean": score,
                "label_mean": label_mean,
                "n": 1,
            }
        )
    return out


def _n_names(rows: Sequence[dict[str, Any]]) -> int:
    names = {
        str(row.get("ticker") or "").upper()
        for row in rows
        if str(row.get("ticker") or "").strip()
        and _finite(row.get("signal_mean")) is not None
        and _finite(row.get("label_mean")) is not None
    }
    return len(names)


def compact_stats(
    summary: Mapping[str, Any],
    *,
    n_names: int,
    signal: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "rank_ic_mean": summary.get("rank_ic_mean"),
        "rank_ic_ir": summary.get("rank_ic_ir"),
        "hit_rate": summary.get("positive_rank_ic_hit_rate"),
        "n_periods": int(summary.get("n_periods") or 0),
        "n_names": int(n_names),
    }
    if signal is not None:
        out["signal"] = signal
    return out


def _period_ic_bundle(
    rows: Sequence[dict[str, Any]],
    tickers: Sequence[str],
    *,
    label: str,
    horizon: str,
    dimension: str,
    signal: str,
) -> tuple[list[str], list[float | None], dict[str, Any]]:
    html = import_sn("rank_ic_html")
    periods = periods_for_cell(
        list(rows),
        label=label,
        horizon=horizon,
        dimension=dimension,
        signal=signal,
    )
    ics = html.period_rank_ics_for_selection(
        list(rows),
        [str(t).upper() for t in tickers],
        label_key=label,
        horizon=horizon,
        dimension=dimension,
        signal=signal,
        periods=periods,
    )
    return periods, list(ics), html.summarize_period_rank_ics(ics)


def evaluate_lab_recipe(
    company_period: Sequence[dict[str, Any]],
    tickers: Sequence[str],
    *,
    label: str,
    horizon: str,
    dimension: str,
    weights: Mapping[str, float],
    baseline_signal: str,
    include_revision: bool = False,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> dict[str, Any]:
    """Lab blend vs production baseline on the active universe."""
    html = import_sn("rank_ic_html")
    universe = [str(t).upper() for t in tickers]
    lab_rows = blend_company_period(
        company_period,
        universe,
        label=label,
        horizon=horizon,
        dimension=dimension,
        weights=weights,
        include_revision=include_revision,
        min_periods=min_periods,
    )
    lab_periods, lab_ics, lab_summary = _period_ic_bundle(
        lab_rows,
        universe,
        label=label,
        horizon=horizon,
        dimension=dimension,
        signal=LAB_BLEND_SIGNAL,
    )
    base_periods, base_ics, base_summary = _period_ic_bundle(
        company_period,
        universe,
        label=label,
        horizon=horizon,
        dimension=dimension,
        signal=baseline_signal,
    )
    all_periods = html.sort_periods(
        list({*lab_periods, *base_periods}),
        "period",
    )
    lab_by_period = dict(zip(lab_periods, lab_ics))
    base_by_period = dict(zip(base_periods, base_ics))
    return {
        "lab_rows": lab_rows,
        "lab": compact_stats(lab_summary, n_names=_n_names(lab_rows)),
        "baseline": compact_stats(
            base_summary,
            n_names=_n_names(
                [
                    row
                    for row in company_period
                    if str(row.get("label_key") or row.get("label") or "") == label
                    and str(row.get("horizon") or "") == horizon
                    and str(row.get("dimension") or "") == dimension
                    and str(row.get("signal") or "") == baseline_signal
                    and str(row.get("ticker") or "").upper() in set(universe)
                ]
            ),
            signal=baseline_signal,
        ),
        "periods": all_periods,
        "lab_period_ics": [lab_by_period.get(period) for period in all_periods],
        "baseline_period_ics": [base_by_period.get(period) for period in all_periods],
    }


def _fmt(value: Any, digits: int = 3) -> str:
    number = _finite(value)
    if number is None:
        return "—"
    return f"{number:+.{digits}f}"


def _fmt_int(value: Any) -> str:
    number = _finite(value)
    if number is None:
        return "—"
    return str(int(number))


def _default_dimension(bundle: RankIcBundle) -> str:
    dims = real_dimensions(bundle.leaderboard or bundle.company_period or bundle.period_ic)
    if "capital_allocation" in dims:
        return "capital_allocation"
    return dims[0] if dims else "demand"


def _plotly_chart(st: Any, figure: Any, *, key: str) -> None:
    try:
        st.plotly_chart(figure, use_container_width=True, key=key)
    except TypeError:
        st.plotly_chart(figure, use_container_width=True)


def _scoreboard_figure(
    periods: Sequence[str],
    lab_ics: Sequence[float | None],
    baseline_ics: Sequence[float | None],
    *,
    baseline_signal: str,
) -> Any:
    import plotly.graph_objects as go  # type: ignore

    z = [list(lab_ics), list(baseline_ics)]
    return go.Figure(
        data=go.Heatmap(
            z=z,
            x=list(periods),
            y=["Lab blend", signal_label(baseline_signal)],
            colorscale="RdBu",
            zmid=0,
            colorbar={"title": "Rank IC"},
            hovertemplate="%{y}<br>period=%{x}<br>Rank IC=%{z:.3f}<extra></extra>",
        )
    ).update_layout(
        title="Period Rank IC · Lab vs baseline",
        xaxis_title="Period",
        height=220,
        margin={"l": 140, "r": 40, "t": 40, "b": 60},
    )


def _apply_pending_session(st: Any, *, labels: Sequence[str], horizons: Sequence[str], dims: Sequence[str]) -> None:
    if st.session_state.pop(_PENDING_RESET_KEY, False):
        for signal in (*CALL_DATE_SIGNALS, REVISION_SIGNAL):
            st.session_state[f"lab_w_{signal}"] = 1.0 if signal == DEFAULT_BASELINE_SIGNAL else 0.0
        st.session_state["lab_include_revision"] = False
        st.session_state["lab_recipe_name"] = ""
        return
    pending = st.session_state.pop(_PENDING_RECIPE_KEY, None)
    if not isinstance(pending, dict):
        return
    weights = pending.get("weights") or {}
    for signal in (*CALL_DATE_SIGNALS, REVISION_SIGNAL):
        if signal in weights:
            st.session_state[f"lab_w_{signal}"] = float(weights[signal])
        elif signal != REVISION_SIGNAL:
            st.session_state[f"lab_w_{signal}"] = 0.0
    st.session_state["lab_include_revision"] = bool(pending.get("include_revision"))
    st.session_state["lab_recipe_name"] = str(pending.get("name") or "")
    label = str(pending.get("label") or "")
    horizon = str(pending.get("horizon") or "")
    dimension = str(pending.get("dimension") or "")
    if label in labels:
        st.session_state["rank_ic_label"] = label
    if horizon in horizons:
        st.session_state["rank_ic_horizon"] = horizon
    if dimension in dims:
        st.session_state["rank_ic_dimension"] = dimension


def _current_weights(st: Any, *, include_revision: bool) -> dict[str, float]:
    weights = default_weights(include_revision=include_revision)
    for signal in CALL_DATE_SIGNALS:
        weights[signal] = float(st.session_state.get(f"lab_w_{signal}", weights[signal]))
    if include_revision:
        weights[REVISION_SIGNAL] = float(
            st.session_state.get(f"lab_w_{REVISION_SIGNAL}", 0.0)
        )
    return weights


def render_lab_filters(
    st: Any,
    bundle: RankIcBundle,
    *,
    universe: Sequence[str],
    available_tickers: Sequence[str],
) -> dict[str, Any]:
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
        signals = [DEFAULT_BASELINE_SIGNAL]
    _apply_pending_session(st, labels=labels, horizons=horizons, dims=dims)

    label_index = labels.index(DEFAULT_LABEL) if DEFAULT_LABEL in labels else 0
    horizon_index = horizons.index(DEFAULT_HORIZON) if DEFAULT_HORIZON in horizons else 0
    default_dim = _default_dimension(bundle)
    dim_index = dims.index(default_dim) if default_dim in dims else 0
    baseline_index = (
        signals.index(DEFAULT_BASELINE_SIGNAL) if DEFAULT_BASELINE_SIGNAL in signals else 0
    )

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
    baseline = c4.selectbox(
        "Baseline (production)",
        signals,
        index=baseline_index,
        format_func=signal_label,
        key="lab_baseline_signal",
    )
    return {
        "label": str(label),
        "horizon": str(horizon),
        "dimension": str(dimension),
        "baseline_signal": str(baseline),
        "universe": list(universe),
        "full_universe": is_full_universe(universe, available_tickers),
    }


def render_weight_sliders(st: Any) -> tuple[dict[str, float], bool]:
    st.subheader("Call-date blend")
    st.caption(
        "Per period, each input is PIT-standardized (expanding, prior periods only), "
        "then blended as sum(w × z) / sum(|w|) with **your** weights — not fitted Rank-IC "
        "weights. History only scales Level vs Quant z so they are comparable."
    )
    if "lab_include_revision" not in st.session_state:
        st.session_state["lab_include_revision"] = False
    include_revision = st.checkbox(
        "Include delayed guidance revision z (T+7, not call-time)",
        key="lab_include_revision",
    )
    signals = list(CALL_DATE_SIGNALS)
    if include_revision:
        signals.append(REVISION_SIGNAL)
    for signal in signals:
        key = f"lab_w_{signal}"
        if key not in st.session_state:
            st.session_state[key] = 1.0 if signal == DEFAULT_BASELINE_SIGNAL else 0.0
    cols = st.columns(3)
    for i, signal in enumerate(signals):
        cols[i % 3].slider(
            signal_label(signal),
            min_value=-2.0,
            max_value=2.0,
            step=0.05,
            key=f"lab_w_{signal}",
        )
    return _current_weights(st, include_revision=include_revision), bool(include_revision)


def _metric_row(st: Any, title: str, stats: Mapping[str, Any]) -> None:
    st.markdown(f"**{title}**")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Rank IC", _fmt(stats.get("rank_ic_mean")))
    m2.metric("IR", _fmt(stats.get("rank_ic_ir")))
    hit = _finite(stats.get("hit_rate"))
    m3.metric("Hit rate", f"{hit:.0%}" if hit is not None else "—")
    m4.metric("n periods", _fmt_int(stats.get("n_periods")))
    m5.metric("n names", _fmt_int(stats.get("n_names")))


def render_scoreboard(st: Any, result: Mapping[str, Any], *, baseline_signal: str) -> None:
    st.subheader("Lab vs production")
    left, right = st.columns(2)
    with left:
        _metric_row(st, "Lab blend", result.get("lab") or {})
    with right:
        _metric_row(
            st,
            f"Baseline · {signal_label(baseline_signal)}",
            result.get("baseline") or {},
        )
    periods = list(result.get("periods") or [])
    if periods:
        _plotly_chart(
            st,
            _scoreboard_figure(
                periods,
                list(result.get("lab_period_ics") or []),
                list(result.get("baseline_period_ics") or []),
                baseline_signal=baseline_signal,
            ),
            key="lab_scoreboard_heatmap",
        )
    st.caption(
        "Deep dissection stays on Rank IC Research. This scoreboard is the Lab "
        "vs production snapshot for the active universe only."
    )


def _recipe_snapshot(
    *,
    name: str,
    uni_key: str,
    filters: Mapping[str, Any],
    weights: Mapping[str, float],
    include_revision: bool,
    recipe_id: str | None = None,
) -> dict[str, Any]:
    snap: dict[str, Any] = {
        "id": recipe_id,
        "name": name,
        "universe_key": uni_key,
        "label": filters["label"],
        "horizon": filters["horizon"],
        "dimension": filters["dimension"],
        "weights": dict(weights),
        "include_revision": include_revision,
    }
    return snap


def render_lab_sidebar(
    st: Any,
    *,
    uni_key: str,
    filters: Mapping[str, Any],
    weights: Mapping[str, float],
    include_revision: bool,
    result: Mapping[str, Any] | None,
) -> None:
    store_path = default_lab_store_path()
    try:
        store = load_lab_store(store_path)
    except LabStoreError as exc:
        st.sidebar.error(str(exc))
        return
    saved = recipes_for(store, uni_key)
    panel = st.sidebar.radio(
        "Lab",
        ["Recipes", "Experiment log"],
        key="lab_sidebar_panel",
    )
    st.sidebar.caption(f"Universe key: `{uni_key}`")
    st.sidebar.caption(f"Store: {store_path}")

    if panel == "Recipes":
        st.sidebar.text_input("Recipe name", key="lab_recipe_name")
        recipe_ids = [""] + [str(r.get("id") or "") for r in saved]
        labels = {
            "": "— load saved —",
            **{
                str(r.get("id") or ""): f"{r.get('name')} · {str(r.get('saved_at') or '')[:10]}"
                for r in saved
            },
        }
        chosen = st.sidebar.selectbox(
            "Saved for this universe",
            recipe_ids,
            format_func=lambda rid: labels.get(str(rid), str(rid)),
            key="lab_load_recipe_id",
        )
        b_new, b_load, b_save = st.sidebar.columns(3)
        if b_new.button("New", key="lab_recipe_new"):
            st.session_state[_PENDING_RESET_KEY] = True
            st.rerun()
        if b_load.button("Load", key="lab_recipe_load"):
            loaded = get_recipe(store, str(chosen)) if chosen else None
            if loaded is None:
                st.sidebar.warning("Pick a saved recipe for this universe.")
            else:
                st.session_state[_PENDING_RECIPE_KEY] = loaded
                st.rerun()
        if b_save.button("Save as", key="lab_recipe_save"):
            name = str(st.session_state.get("lab_recipe_name") or "").strip()
            if not name:
                st.sidebar.warning("Name the recipe before saving.")
            else:
                saved_row = upsert_recipe(
                    store,
                    name=name,
                    universe_key_value=uni_key,
                    label=str(filters["label"]),
                    horizon=str(filters["horizon"]),
                    dimension=str(filters["dimension"]),
                    weights=weights,
                    include_revision=include_revision,
                )
                try:
                    save_lab_store(store, store_path)
                except LabStoreError as exc:
                    st.sidebar.error(str(exc))
                    return
                st.sidebar.success(f"Saved `{saved_row['name']}`.")

        tag = st.sidebar.selectbox(
            "Trial tag",
            ["unset", "good", "bad"],
            key="lab_trial_tag",
        )
        if st.sidebar.button("Log trial", key="lab_log_trial"):
            if result is None:
                st.sidebar.warning("Nothing to log yet.")
            else:
                name = str(st.session_state.get("lab_recipe_name") or "").strip() or "Untitled recipe"
                snap = _recipe_snapshot(
                    name=name,
                    uni_key=uni_key,
                    filters=filters,
                    weights=weights,
                    include_revision=include_revision,
                    recipe_id=str(chosen) if chosen else None,
                )
                append_trial(
                    store,
                    recipe=snap,
                    lab_stats=dict(result.get("lab") or {}),
                    baseline_stats=dict(result.get("baseline") or {}),
                    tag=None if tag == "unset" else tag,
                )
                try:
                    save_lab_store(store, store_path)
                except LabStoreError as exc:
                    st.sidebar.error(str(exc))
                    return
                st.sidebar.success("Trial logged.")
    else:
        rows = trials_for(store, uni_key, limit=25)
        if not rows:
            st.sidebar.info("No trials logged for this universe yet.")
        else:
            display = [
                {
                    "when": str(t.get("logged_at") or "")[:19],
                    "name": t.get("recipe_name"),
                    "tag": t.get("tag") or "",
                    "lab IC": _fmt((t.get("lab") or {}).get("rank_ic_mean")),
                    "base IC": _fmt((t.get("baseline") or {}).get("rank_ic_mean")),
                }
                for t in rows
            ]
            try:
                import pandas as pd  # type: ignore

                st.sidebar.dataframe(pd.DataFrame(display), hide_index=True, use_container_width=True)
            except Exception:  # noqa: BLE001
                st.sidebar.write(display)

    st.sidebar.caption(
        "Co-pilot (later): reads this experiment log and warns when a recipe "
        "looks like a known false win. Not built in v1."
    )
    st.sidebar.caption(
        "Promotion (later): gated copy into a sector default or production_v2. "
        "Lab never writes the production pack."
    )


def render_rank_ic_lab(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    universe = _universe(data, sector_tickers)
    uni_key = universe_key(sector_choice, universe)
    bundle = load_rank_ic_bundle()
    st.caption(
        "What-if sandbox only. The production pack is unchanged. Rank IC Research "
        "is where you dissect a cell; Lab is where you try a recipe on stored "
        "`company_period` rows — not a live rescoring of transcripts."
    )
    path_id = load_path_id_v1()
    if path_id is not None:
        render_path_id_panel(st, path_id, desk=load_desk_path_id_v1())
        render_claims_desk_panel(st, load_desk_claims_v1())
    if not bundle.available:
        st.info(bundle.empty_message)
        if bundle.missing:
            st.caption("Missing: " + ", ".join(bundle.missing[:4]))
        render_lab_sidebar(
            st,
            uni_key=uni_key,
            filters={
                "label": DEFAULT_LABEL,
                "horizon": DEFAULT_HORIZON,
                "dimension": "demand",
            },
            weights=default_weights(),
            include_revision=False,
            result=None,
        )
        return
    if not bundle.company_period:
        st.warning(
            "Lab needs `narrative_signal_eval_company_period.csv`. "
            "Run evaluate_narrative_signals.py, or "
            "`python scripts/_rebuild_rank_ic_html.py` to extract it from the HTML report."
        )
        render_lab_sidebar(
            st,
            uni_key=uni_key,
            filters={
                "label": DEFAULT_LABEL,
                "horizon": DEFAULT_HORIZON,
                "dimension": "demand",
            },
            weights=default_weights(),
            include_revision=False,
            result=None,
        )
        return

    generated = bundle.meta.get("generated_at")
    if generated:
        st.caption(f"Artifacts generated {generated}")

    filters = render_lab_filters(
        st,
        bundle,
        universe=universe,
        available_tickers=data.tickers,
    )
    st.caption("Label, horizon, and dimension are shared with Rank IC Research.")
    st.caption(
        f"{label_display(filters['label'])} · {filters['horizon']} · "
        f"{dimension_label(filters['dimension'])} · "
        f"baseline {signal_label(filters['baseline_signal'])} · "
        f"{len(filters['universe'])} companies"
    )
    weights, include_revision = render_weight_sliders(st)
    result: dict[str, Any] | None = None
    if filters["dimension"] == ALL_MEAN:
        st.warning(all_mean_blocked_message())
    elif not active_weights(weights, include_revision=include_revision):
        st.info("Turn on at least one weight to blend a Lab signal.")
    else:
        result = evaluate_lab_recipe(
            bundle.company_period,
            filters["universe"],
            label=filters["label"],
            horizon=filters["horizon"],
            dimension=filters["dimension"],
            weights=weights,
            baseline_signal=filters["baseline_signal"],
            include_revision=include_revision,
        )
        render_scoreboard(st, result, baseline_signal=filters["baseline_signal"])

    render_lab_sidebar(
        st,
        uni_key=uni_key,
        filters=filters,
        weights=weights,
        include_revision=include_revision,
        result=result,
    )
