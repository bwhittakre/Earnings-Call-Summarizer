"""Streamlit renderers.

No Streamlit import occurs here.  A compatible object is passed in by the app,
which keeps these functions importable and easy to exercise in unit tests.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Sequence
from urllib.parse import urlencode

from .charts import (
    heatmap_chart,
    narrative_quant_gap_timeseries_plotly,
    narrative_quant_plotly,
    overview_pulse_chart,
    ranked_bar_chart,
)
from .nvq_analytics import (
    calendar_quarter_options,
    filter_by_calendar_quarters,
    point_key,
)
from .company_labels import format_company_label, with_company_labels
from .data import DashboardData
from .report_static import ensure_reports_static_link, static_report_url
from .research_data import (
    artifact_universe_status,
    can_inline_html,
    format_universe_stale_message,
    html_report_meta,
    load_book_ranks_bundle,
    load_consolidated_panel,
    load_rank_ic_bundle,
    resolve_book_ranks_html,
    resolve_consolidated_html,
)
from .rank_ic_research import RANK_IC_VIEWS  # noqa: F401

_BOOK_RANKS_METRIC_KEY = (
    (
        "Rank (1=highest)",
        "Dense rank within eligible peers for this hypothesis. 1 is strongest.",
    ),
    (
        "Cross-section z",
        "Z-score of the raw signal vs peers in the same period bucket.",
    ),
    (
        "Raw signal",
        "Call-day feature value used for ranking (quant_z_pit / agrees_with_quant).",
    ),
    (
        "Peer count",
        "Eligible book names in the cross-section for this hypothesis.",
    ),
    (
        "Eligible",
        "False when excluded (first-print, missing prior, not investable, missing signal).",
    ),
)
from .sectors import (
    ALL_COMPANIES,
    CUSTOM_LIST,
    is_full_universe,
    pad_company_rows,
)

_HEATMAP_MAX_COMPARE = 4
_HTML_EMBED_HEIGHT = 1000

_SIGNAL_LABELS = {
    "Narrative level": "narrative_level",
    "Quant z-score": "quant_z",
    "Surprise–quant gap": "gap",
}

_CROSS_SIGNAL_LABELS = {
    "Mean narrative": "mean_narrative_level",
    "Mean quant z": "mean_quant_z",
    "Mean surprise–quant gap": "mean_narrative_quant_gap",
    "Mean change": "mean_narrative_change",
    "Divergence rate": "divergence_rate",
}


def _universe(
    data: DashboardData, sector_tickers: Sequence[str] | None
) -> list[str]:
    if sector_tickers is not None:
        return [str(ticker).upper() for ticker in sector_tickers]
    return list(data.tickers)


def _research_iframe_query(
    data: DashboardData,
    universe: Sequence[str],
    *,
    sector_choice: str | None,
) -> dict[str, str] | None:
    """Build ``?tickers=`` / ``?preset=`` for research HTML embeds."""
    query: dict[str, str] = {}
    if universe and not is_full_universe(universe, data.tickers):
        query["tickers"] = ",".join(str(t).upper() for t in universe if str(t).strip())
    choice = (sector_choice or "").strip()
    if choice and choice not in {ALL_COMPANIES, CUSTOM_LIST}:
        query["preset"] = choice
    return query or None


def _table(st: Any, rows: list[dict[str, Any]]) -> None:
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No matching records.")


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def _select_ticker(
    st: Any,
    tickers: Sequence[str],
    *,
    label: str = "Company",
    key: str | None = None,
) -> str:
    kwargs: dict[str, Any] = {"format_func": format_company_label}
    if key is not None:
        kwargs["key"] = key
    return st.selectbox(label, list(tickers), **kwargs)


def _multi_tickers(
    st: Any,
    tickers: Sequence[str],
    *,
    label: str = "Companies",
    default: Sequence[str] | None = None,
    key: str | None = None,
    max_selections: int | None = None,
) -> list[str]:
    options = list(tickers)
    chosen_default = list(default if default is not None else options)
    if max_selections is not None:
        chosen_default = chosen_default[:max_selections]
    kwargs: dict[str, Any] = {
        "default": chosen_default,
        "format_func": format_company_label,
        "max_selections": max_selections,
    }
    if key is not None:
        kwargs["key"] = key
    # Streamlit <1.28 may not support max_selections; fall back gracefully.
    try:
        return list(st.multiselect(label, options, **kwargs))
    except TypeError:
        kwargs.pop("max_selections", None)
        selected = list(st.multiselect(label, options, **kwargs))
        if max_selections is not None and len(selected) > max_selections:
            st.warning(f"Showing the first {max_selections} selected companies.")
            return selected[:max_selections]
        return selected


def _altair(st: Any, chart: Any) -> None:
    try:
        st.altair_chart(chart, use_container_width=True)
    except Exception as exc:  # noqa: BLE001 — surface chart dependency issues in UI
        st.caption(f"Unable to render chart: {exc}")


def _render_html_report(
    st: Any,
    path: Path | None,
    *,
    missing_hint: str,
    iframe_query: dict[str, str] | None = None,
) -> bool:
    """Embed a self-contained HTML report. Returns True when rendered.

    Large reports (e.g. full consolidated_feature_panel.html) are iframed from
    Streamlit static serving so we never fall back to a smaller 4-ticker HTML.
    """
    if path is None or not path.is_file():
        st.info(missing_hint)
        return False
    meta = html_report_meta(path)
    size_mb = (meta.get("size_bytes") or 0) / (1024 * 1024)
    st.caption(
        f"Report: {meta.get('stem') or path.name} · "
        f"Generated: {meta.get('generated_at') or '—'} · "
        f"{size_mb:.1f} MB · Path: {meta.get('path')}"
    )

    try:
        import streamlit.components.v1 as components  # type: ignore
    except Exception:  # noqa: BLE001
        components = getattr(getattr(st, "components", None), "v1", None)

    # Prefer static iframe (Compose mounts reports into dashboard/static/reports).
    static_dir = ensure_reports_static_link()
    use_static = static_dir is not None and (static_dir / path.name).exists()
    if use_static and components is not None:
        try:
            # Cache-bust: browsers aggressively cache this ~90MB HTML; without a
            # version query, regenerating the report is invisible in the iframe.
            query: dict[str, str] = dict(iframe_query or {})
            try:
                query["v"] = str(int(path.stat().st_mtime))
            except OSError:
                query["v"] = "1"
            iframe_src = f"{static_report_url(path.name)}?{urlencode(query)}"
            components.iframe(
                iframe_src,
                height=_HTML_EMBED_HEIGHT,
                scrolling=True,
            )
            return True
        except Exception:  # noqa: BLE001
            pass

    if not can_inline_html(path):
        st.warning(
            f"Report is {size_mb:.1f} MB and static serving is unavailable. "
            "Enable Streamlit static serving (`--server.enableStaticServing=true`) "
            "or open the HTML file from the path above."
        )
        return False

    try:
        html_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        st.warning(f"Unable to read report: {exc}")
        return False
    if components is None:
        st.warning("Streamlit components unavailable; cannot embed HTML report.")
        return False
    try:
        components.html(html_text, height=_HTML_EMBED_HEIGHT, scrolling=True)
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Unable to embed HTML report: {exc}")
        return False
    return True


def render_overview(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    st.header("Roz overview")
    universe = _universe(data, sector_tickers)
    summary = data.overview()
    companies, quarters, active, incomplete = st.columns(4)
    companies.metric("Companies (sector)", len(universe))
    quarters.metric("Historical quarters", summary["quarters"])
    active.metric("Active events", summary["active_events"])
    incomplete.metric("Incomplete quarters", summary["incomplete_quarters"])
    st.caption(
        f"{summary['history_rows']:,} dimension records are loaded across "
        f"{summary['armed_events']} operational events. "
        f"Comparative views use the Sector filter ({len(universe)} companies)."
    )

    st.subheader("Latest company scorecards")
    scorecards = [
        row
        for row in data.latest_scorecards()
        if str(row.get("ticker", "")).upper() in set(universe)
    ]
    scorecards = pad_company_rows(scorecards, universe)
    _table(
        st,
        [
            {
                "company": format_company_label(row["ticker"]),
                "latest_period": row.get("fiscal_period"),
                "narrative": _fmt(row.get("narrative_level")),
                "change": _fmt(row.get("narrative_change")),
                "quant_z": _fmt(row.get("quant_z")),
                "surprise_quant_gap": _fmt(row.get("narrative_quant_gap")),
                "divergences": row.get("divergences"),
                "dimensions": row.get("dimensions"),
                "incomplete": row.get("incomplete"),
                "quant_ok": row.get("quant_quality_ok", True),
                "quant_flags": ", ".join(row.get("quant_quality_flags") or ()) or "—",
            }
            for row in scorecards
        ],
    )
    flagged = [row for row in scorecards if row.get("quant_flagged")]
    if flagged:
        st.caption(
            "Quant quality flags mark quarters where consensus was too small for a "
            "percent surprise or a member measure was suppressed. Charts use the "
            "clean decision quant_z."
        )

    st.subheader("Universe pulse")
    pulse = pad_company_rows(data.overview_pulse(), universe)
    # Re-sort after padding: largest abs gap first, nulls last.
    pulse.sort(
        key=lambda item: (
            item.get("abs_gap") is None,
            -(item.get("abs_gap") or 0.0),
            str(item.get("ticker", "")),
        )
    )
    if pulse:
        _altair(st, overview_pulse_chart(pulse))
        st.caption(
            "Gap = narrative surprise − quant z (latest print), with quant clipped "
            "to ±2 before subtracting. It is not narrative level − quant z — level "
            "is shown in the tooltip for context only. "
            "Ranked by absolute gap; every company in the Sector filter is shown "
            "(grey = gap unavailable). Flagged = severe quant issues "
            "(near-zero consensus / member suppressed), not routine sparse dimensions. "
            "Deep dive: Narrative vs quant / Dimension panel."
        )
    else:
        st.info("No latest scorecards available for the pulse chart.")

    st.subheader("Historical completeness")
    coverage = [
        row
        for row in data.completeness_coverage()
        if str(row.get("ticker", "")).upper() in set(universe)
    ]
    _table(st, with_company_labels(coverage))
    events = data.event_inbox()
    if events:
        st.subheader("Recent pipeline events")
        _table(st, with_company_labels(events[:8]))
    alerts = data.operational_alerts()
    if alerts:
        st.subheader("Operational alerts")
        _table(st, with_company_labels(alerts))


def render_event_inbox(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    del sector_tickers, sector_choice  # ops view is not sector-scoped
    st.header("Event inbox")
    events = data.event_inbox()
    statuses = sorted({str(event.get("status")) for event in events if event.get("status")})
    status = st.selectbox("Status", ("all", *statuses))
    if status != "all":
        events = [event for event in events if event["status"] == status]
    _table(st, with_company_labels(events))


def render_company_history(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    st.header("Company history")
    universe = _universe(data, sector_tickers) or list(data.tickers)
    if not universe:
        st.info("No companies are available.")
        return
    ticker = _select_ticker(st, universe)
    history = data.company_history(ticker)
    flagged = sum(bool(row.get("quant_flagged")) for row in history)
    st.caption(
        f"{format_company_label(ticker)} · {len(history)} imported quarters"
        + (f"; {flagged} with quant quality flags" if flagged else "")
    )
    _table(
        st,
        [
            {
                "fiscal_period": row["fiscal_period"],
                "dimensions": row.get("dimensions"),
                "narrative_level": row.get("narrative_level"),
                "narrative_change": row.get("narrative_change"),
                "quant_z": row.get("quant_z"),
                "surprise_quant_gap": row.get("narrative_quant_gap"),
                "divergences": row.get("divergences"),
                "incomplete": row.get("incomplete"),
                "quant_ok": row.get("quant_quality_ok", True),
                "quant_flags": ", ".join(row.get("quant_quality_flags") or ())
                or "—",
            }
            for row in history
        ],
    )
    chart_rows = [
        {
            "fiscal_period": row["fiscal_period"],
            "narrative_level": row["narrative_level"],
            "quant_z": row["quant_z"],
            "surprise_quant_gap": row["narrative_quant_gap"],
        }
        for row in history
    ]
    if chart_rows:
        st.line_chart(
            chart_rows,
            x="fiscal_period",
            y=["narrative_level", "quant_z", "surprise_quant_gap"],
        )
        st.caption(
            "surprise_quant_gap = narrative surprise − quant z (quant clipped to ±2), "
            "not level − quant."
        )


def render_dimension_heatmap(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    st.header("Dimension panel")
    universe = _universe(data, sector_tickers)
    if not universe:
        st.info("No companies are available.")
        return

    mode = st.radio("Mode", ("Single", "Compare"), horizontal=True, key="dim_mode")
    if mode == "Single":
        selected = [_select_ticker(st, universe, key="dim_single_company")]
        facet = False
    else:
        selected = _multi_tickers(
            st,
            universe,
            default=universe[: min(2, len(universe))],
            key="dim_compare_companies",
            max_selections=_HEATMAP_MAX_COMPARE,
        )
        if not selected:
            st.info("Select up to four companies to compare.")
            return
        if len(selected) > _HEATMAP_MAX_COMPARE:
            selected = selected[:_HEATMAP_MAX_COMPARE]
            st.warning(f"Compare mode shows at most {_HEATMAP_MAX_COMPARE} companies.")
        facet = len(selected) > 1

    periods = st.slider("Latest periods", min_value=4, max_value=20, value=8)
    metric_label = st.radio(
        "Signal",
        tuple(_SIGNAL_LABELS),
        horizontal=True,
        key="dim_signal",
    )
    metric = _SIGNAL_LABELS[metric_label]
    rows = data.dimension_heatmap(
        tickers=selected,
        latest_periods=periods,
    )
    if not rows:
        st.info("No dimension history matches the selected companies.")
        return

    center_zero = metric in {"quant_z", "gap"}
    _altair(
        st,
        heatmap_chart(
            rows,
            metric,
            title=f"{metric_label} · {' / '.join(format_company_label(t) for t in selected)}",
            facet_by_company=facet,
            center_zero=center_zero,
        ),
    )
    st.caption(
        "X-axis uses period-end calendar quarters (aligned across companies, same "
        "convention as Consolidated / Signal research). Fiscal period is in the "
        "tooltip. Color scales are fixed (narrative [-2, +2]; quant z / gap [-3, +3])."
    )
    _table(
        st,
        [
            {
                "company": format_company_label(row["ticker"]),
                "calendar_quarter": row.get("calendar_quarter"),
                "fiscal_period": row["fiscal_period"],
                "dimension": row["dimension"],
                metric: row[metric],
                "divergence": row["divergence"],
            }
            for row in rows
        ],
    )


def render_cross_company(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    st.header("Cross-company")
    universe = _universe(data, sector_tickers)
    periods = st.slider("Trailing quarters", min_value=1, max_value=40, value=12)
    signal_label = st.selectbox("Signal", list(_CROSS_SIGNAL_LABELS), key="cross_signal")
    signal_col = _CROSS_SIGNAL_LABELS[signal_label]
    scope_options = ["All dimensions (avg)", *data.dimensions]
    scope = st.selectbox("Scope", scope_options, key="cross_scope")
    dimension = None if scope == "All dimensions (avg)" else scope

    rows = data.cross_company(latest_periods=periods, dimension=dimension)
    rows = pad_company_rows(rows, universe)
    if not rows:
        st.info("No cross-company history is available.")
        return

    st.caption(
        f"Window: last {periods} quarters · Scope: {scope} · "
        f"Sector: {len(universe)} companies (all listed) · Ranking by {signal_label}."
    )
    _altair(
        st,
        ranked_bar_chart(
            rows,
            signal_col,
            title=f"{signal_label} · {scope}",
            sort_abs=signal_col == "mean_narrative_quant_gap",
        ),
    )

    table_rows = []
    for row in rows:
        ordered = {
            "company": format_company_label(row["ticker"]),
            signal_col: row.get(signal_col),
            "latest_period": row.get("latest_period"),
            "quarters": row.get("quarters"),
            "scope": row.get("scope"),
            "mean_narrative_level": row.get("mean_narrative_level"),
            "mean_quant_z": row.get("mean_quant_z"),
            "mean_narrative_quant_gap": row.get("mean_narrative_quant_gap"),
            "mean_narrative_change": row.get("mean_narrative_change"),
            "divergence_rate": row.get("divergence_rate"),
            "incomplete_quarters": row.get("incomplete_quarters"),
        }
        table_rows.append(ordered)
    table_rows.sort(
        key=lambda item: (
            item.get(signal_col) is None,
            -(abs(item[signal_col]) if isinstance(item.get(signal_col), (int, float)) else 0)
            if signal_col == "mean_narrative_quant_gap"
            else (-(item[signal_col]) if isinstance(item.get(signal_col), (int, float)) else 0),
        )
    )
    _table(st, table_rows)


def _nvq_selection_keys(event: Any) -> list[str]:
    """Extract stable point keys from a Streamlit Plotly selection event."""
    if event is None:
        return []
    selection = getattr(event, "selection", None)
    if selection is None and isinstance(event, dict):
        selection = event.get("selection")
    points = getattr(selection, "points", None)
    if points is None and isinstance(selection, dict):
        points = selection.get("points")
    if not points:
        return []
    keys: list[str] = []
    for point in points:
        if isinstance(point, dict):
            custom = point.get("customdata")
            point_id = point.get("id") or point.get("point_id")
        else:
            custom = getattr(point, "customdata", None)
            point_id = getattr(point, "id", None) or getattr(point, "point_id", None)
        if isinstance(custom, (list, tuple)) and custom:
            # customdata last slot is point_id in scatter and gap-over-time
            candidate = custom[-1]
            if isinstance(candidate, str) and "|" in candidate:
                keys.append(candidate)
                continue
        if point_id:
            keys.append(str(point_id))
    # Preserve order, drop dupes
    seen: set[str] = set()
    ordered: list[str] = []
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def _nvq_plotly_chart(st: Any, figure: Any, *, key: str) -> Any:
    """Render Plotly with selection + scrollZoom; fall back if API unsupported."""
    kwargs = {
        "use_container_width": True,
        "config": {"scrollZoom": True},
        "key": key,
    }
    try:
        return st.plotly_chart(
            figure,
            on_select="rerun",
            selection_mode=("points", "box", "lasso"),
            **kwargs,
        )
    except TypeError:
        # Older Streamlit without selection API.
        return st.plotly_chart(figure, **kwargs)


def render_narrative_vs_quant(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    st.header("Narrative vs quant")
    universe = _universe(data, sector_tickers)
    if not universe:
        st.info("No companies are available.")
        return

    if "nvq_selection" not in st.session_state:
        st.session_state["nvq_selection"] = []

    default = universe[:1]
    selected = _multi_tickers(
        st,
        universe,
        default=default,
        key="nvq_companies",
    )
    chart_tickers = selected or default
    peer_universe = list(universe)

    mode = st.radio(
        "Mode",
        ("Scatter", "Gap over time"),
        horizontal=True,
        key="nvq_mode",
    )
    gap_kind = "level"
    if mode == "Gap over time":
        gap_label = st.radio(
            "Gap series",
            ("Level gap", "Surprise gap"),
            horizontal=True,
            key="nvq_gap_kind",
        )
        gap_kind = "surprise" if gap_label == "Surprise gap" else "level"
        if gap_kind == "level":
            st.caption(
                "How call tone for this dimension compares to the quant print "
                "(positive = narrative hotter than quant)."
            )
        else:
            st.caption(
                "How narrative surprise compares to Quant z (Quant z clipped to ±3). "
                "Positive = surprise more bullish than quant."
            )
    dimension_options = ["All"] + data.dimensions
    if mode == "Gap over time":
        dimension_options = list(data.dimensions) or ["demand"]
    dimension = st.selectbox("Dimension", dimension_options, key="nvq_dimension")
    if mode == "Gap over time" and dimension == "All":
        dimension = dimension_options[0]

    dim_filter = None if dimension == "All" else dimension
    base_points = data.narrative_vs_quant(
        tickers=chart_tickers,
        dimension=dim_filter,
        peer_tickers=peer_universe,
    )
    period_options = calendar_quarter_options(base_points)
    selected_periods = st.multiselect(
        "Calendar quarters",
        period_options,
        default=period_options,
        key="nvq_calendar_quarters",
        help="Uses period-end calendar quarter so peers align across fiscal calendars.",
    )
    agreement = st.radio(
        "Agreement",
        ("All", "Aligned only", "Divergences only"),
        horizontal=True,
        key="nvq_agreement",
    )
    peer_outliers = st.checkbox(
        "Peer outliers only (|peer gap Δ| ≥ 0.5)",
        value=False,
        key="nvq_peer_outliers",
    )
    streak_cols = st.columns(2)
    streak_type = streak_cols[0].selectbox(
        "Streak type",
        ("Any", "Divergent", "Aligned"),
        key="nvq_streak_type",
    )
    min_streak = int(
        streak_cols[1].number_input(
            "Min streak length",
            min_value=1,
            value=1,
            step=1,
            key="nvq_min_streak",
        )
    )

    points = filter_by_calendar_quarters(base_points, selected_periods)
    if agreement == "Aligned only":
        points = [point for point in points if point.get("agreement") == "Aligned"]
    elif agreement == "Divergences only":
        points = [point for point in points if point.get("agreement") == "Divergence"]
    if peer_outliers:
        points = [
            point
            for point in points
            if isinstance(point.get("peer_gap_delta"), (int, float))
            and abs(float(point["peer_gap_delta"])) >= 0.5
        ]
    if min_streak > 1 or streak_type != "Any":
        filtered: list[dict[str, Any]] = []
        for point in points:
            diverge = int(point.get("diverge_streak") or 0)
            align = int(point.get("align_streak") or 0)
            if streak_type == "Divergent":
                ok = diverge >= min_streak
            elif streak_type == "Aligned":
                ok = align >= min_streak
            else:
                ok = max(diverge, align) >= min_streak
            if ok:
                filtered.append(point)
        points = filtered

    if mode == "Gap over time" and len(chart_tickers) > 6:
        st.warning(
            "Gap over time is clearest with ≤6 companies — narrowing display."
        )
        chart_tickers = list(chart_tickers)[:6]
        allowed = {ticker.upper() for ticker in chart_tickers}
        points = [
            point for point in points if str(point.get("ticker", "")).upper() in allowed
        ]

    divergences = sum(bool(point.get("divergence")) for point in points)
    flips = sum(bool(point.get("agreement_flipped")) for point in points)
    peer_outlier_n = sum(
        1
        for point in points
        if isinstance(point.get("peer_gap_delta"), (int, float))
        and abs(float(point["peer_gap_delta"])) >= 0.5
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Points", len(points))
    m2.metric("Divergences", divergences)
    m3.metric("Flips", flips)
    m4.metric("Peer outliers", peer_outlier_n)

    selected_keys = list(st.session_state.get("nvq_selection") or [])
    if points:
        if mode == "Gap over time":
            figure = narrative_quant_gap_timeseries_plotly(
                points,
                gap_kind=gap_kind,
                selected_keys=selected_keys,
            )
        else:
            figure = narrative_quant_plotly(
                points,
                color_by_company=len(chart_tickers) > 1,
                selected_keys=selected_keys,
            )
        event = _nvq_plotly_chart(st, figure, key="nvq_plotly")
        event_keys = _nvq_selection_keys(event)
        if event_keys:
            st.session_state["nvq_selection"] = event_keys
            selected_keys = event_keys

        clear_cols = st.columns([1, 3])
        if clear_cols[0].button("Clear selection", key="nvq_clear_selection"):
            st.session_state["nvq_selection"] = []
            selected_keys = []
        if selected_keys:
            clear_cols[1].caption(
                f"Working set: {len(selected_keys)} selected point(s). "
                "Table/CSV follow the selection."
            )
        else:
            clear_cols[1].caption(
                "Scroll/pinch zooms the plot (hover first); double-click resets. "
                "Box/lasso or click to build a working set."
            )
        st.caption(
            "Peer stats use the Sector sidebar universe, grouped by calendar quarter × "
            "dimension. Streaks require consecutive calendar quarters; a missing quarter "
            "breaks the streak. Flipped points use a darker marker outline."
        )

        key_set = set(selected_keys)
        working = (
            [point for point in points if point_key(point) in key_set]
            if key_set
            else points
        )
        sorted_points = sorted(
            working,
            key=lambda point: (
                not bool(point.get("divergence")),
                str(point.get("ticker")),
                str(point.get("calendar_quarter") or point.get("fiscal_period")),
            ),
        )
        table_rows = with_company_labels(sorted_points)
        _table(st, table_rows)
        try:
            import pandas as pd  # type: ignore

            csv_bytes = pd.DataFrame(table_rows).to_csv(index=False).encode("utf-8")
            st.download_button(
                "Download CSV",
                data=csv_bytes,
                file_name="narrative_vs_quant_working_set.csv",
                mime="text/csv",
                key="nvq_download_csv",
            )
        except Exception:  # noqa: BLE001
            pass
    else:
        st.info("No rows have both narrative and quantitative values for this filter.")


def _warn_research_universe(st: Any, data: DashboardData) -> None:
    """Surface Rank IC / consolidated ticker lag vs the loaded parquet dataset."""
    rank_ic = load_rank_ic_bundle()
    consolidated = load_consolidated_panel()
    status = artifact_universe_status(
        data.tickers,
        rank_ic.meta if rank_ic.available else None,
        consolidated.meta if consolidated.available else None,
    )
    message = format_universe_stale_message(status)
    if message:
        st.warning(message)


def render_book_ranks(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    del data, sector_tickers, sector_choice
    st.header("Book ranks")
    st.caption(
        "Cross-sectional ranks for the frozen production signal pack "
        "(``production_v1``), published at investable-as-of (bucket T+7). "
        "Filter by hypothesis/ticker; metric key is on the right."
    )
    html_path = resolve_book_ranks_html()
    if html_path is not None:
        _render_html_report(
            st,
            html_path,
            missing_hint="",
        )
        return

    bundle = load_book_ranks_bundle()
    if not bundle.available:
        st.info(bundle.empty_message)
        if bundle.missing:
            st.caption("Missing: " + ", ".join(bundle.missing[:3]))
        return
    meta = bundle.meta
    st.caption(
        f"pack={meta.get('pack_id') or '—'} · "
        f"period_bucket={meta.get('period_bucket') or '—'} · "
        f"n_peers={meta.get('n_peers') if meta.get('n_peers') is not None else '—'} · "
        f"built_at={meta.get('built_at') or meta.get('generated_at') or '—'}"
    )
    if meta.get("trigger_ticker"):
        st.caption(
            f"Last trigger: {meta.get('trigger_ticker')} "
            f"{meta.get('trigger_period') or ''}".strip()
        )
    if meta.get("skipped_reason"):
        st.warning(f"Last build skipped: {meta['skipped_reason']}")
    rows = list(bundle.rows)
    if not rows:
        st.info("Summary present but no rank rows (peer set below min_names).")
        return

    hyp_labels = ["All hypotheses"] + sorted(
        {
            f"{r.get('signal')} × {r.get('dimension')}"
            for r in rows
            if r.get("signal") and r.get("dimension")
        }
    )
    left, right = st.columns([3, 1])
    with left:
        c1, c2, c3 = st.columns([2, 2, 1])
        choice = c1.selectbox("Hypothesis", hyp_labels, key="book_ranks_hyp")
        ticker_q = c2.text_input("Ticker contains", value="", key="book_ranks_q")
        eligible_only = c3.checkbox("Eligible only", value=True, key="book_ranks_elig")

        filtered = list(rows)
        if choice != "All hypotheses":
            signal, _, dimension = choice.partition(" × ")
            filtered = [
                r
                for r in filtered
                if str(r.get("signal")) == signal and str(r.get("dimension")) == dimension
            ]
        query = ticker_q.strip().upper()
        if query:
            filtered = [
                r
                for r in filtered
                if query in str(r.get("ticker") or "").upper()
            ]
        if eligible_only:
            filtered = [
                r
                for r in filtered
                if r.get("eligible") in (True, "True", "true", 1)
            ]
        trigger = str(meta.get("trigger_ticker") or "").upper()

        def _sort_key(row: dict[str, Any]) -> tuple:
            rank = row.get("rank")
            try:
                rank_i = (
                    int(float(rank))
                    if rank is not None and str(rank) != "nan"
                    else 10**9
                )
            except (TypeError, ValueError):
                rank_i = 10**9
            return (
                str(row.get("dimension") or ""),
                str(row.get("signal") or ""),
                rank_i,
                str(row.get("ticker") or ""),
            )

        filtered = sorted(filtered, key=_sort_key)
        display = []
        for row in filtered:
            ticker = str(row.get("ticker") or "").upper()
            display.append(
                {
                    "Ticker": f"→ {ticker}" if trigger and ticker == trigger else ticker,
                    "Fiscal period": row.get("fiscal_period"),
                    "Hypothesis": f"{row.get('signal')} × {row.get('dimension')}",
                    "Rank (1=highest)": row.get("rank"),
                    "Cross-section z": row.get("cs_z"),
                    "Raw signal": row.get("raw"),
                    "Peer count": row.get("n_peers"),
                    "Eligible": row.get("eligible"),
                }
            )
        st.caption(f"Showing {len(display)} of {len(rows)} rows")
        if display:
            try:
                import pandas as pd  # type: ignore

                st.dataframe(
                    pd.DataFrame(display),
                    use_container_width=True,
                    hide_index=True,
                    height=min(560, 48 + 28 * max(len(display), 4)),
                )
            except Exception:  # noqa: BLE001
                _table(st, display)
        else:
            st.info("No rows match the current filters.")
    with right:
        st.subheader("Metric key")
        for title, body in _BOOK_RANKS_METRIC_KEY:
            st.markdown(f"**{title}**  \n{body}")


def render_consolidated_panel(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    universe = _universe(data, sector_tickers)
    st.header("Consolidated panel")
    st.caption(
        "Embedded consolidated feature panel "
        "(``consolidated_feature_panel.html`` / ``cross_section_panel.html``). "
        "The Sector sidebar filter scopes the company list when it is narrower "
        "than the full dataset."
    )
    _warn_research_universe(st, data)
    if universe and not is_full_universe(universe, data.tickers):
        missing = sorted(set(data.tickers) - set(universe))
        if missing:
            st.warning(
                f"Sector filter excludes {len(missing)} loaded companies: "
                f"{', '.join(missing)}. Update the sector book or choose All Companies."
            )
        st.caption(
            f"Showing {len(universe)} of {len(data.tickers)} companies from the "
            f"Sector filter: {', '.join(universe)}."
        )
    path = resolve_consolidated_html()
    _render_html_report(
        st,
        path,
        missing_hint=(
            "Consolidated panel HTML not found under cross_company/reports/. "
            "Expected consolidated_feature_panel.html (full universe). Run: "
            "python build_consolidated_panel_report.py --tickers <universe> "
            "--min-calendar-quarter 2016-Q2"
        ),
        iframe_query=_research_iframe_query(
            data, universe, sector_choice=sector_choice
        ),
    )


def render_audit(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    del sector_tickers, sector_choice
    st.header("Audit")
    incomplete_only = st.checkbox("Show incomplete quarters only", value=False)
    audits = data.audit(incomplete_only=incomplete_only)
    incomplete = sum(bool(row["incomplete"]) for row in audits)
    left, right = st.columns(2)
    left.metric("Quarter records", len(audits))
    right.metric("Incomplete", incomplete)
    _table(st, with_company_labels(audits))
    st.subheader("Pipeline status")
    status = data.pipeline_status()
    if status:
        _table(st, with_company_labels(status))
    else:
        st.caption("No operational events are armed.")


def render_operations(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
    sector_choice: str | None = None,
) -> None:
    del sector_tickers, sector_choice
    st.header("Operations")
    alerts = data.operational_alerts()
    left, right = st.columns(2)
    left.metric("Active alerts", len(alerts))
    right.metric("Recorded runs", len(data.job_runs))

    host = data.host_feed_status()
    st.subheader("Host feed")
    if host.get("available"):
        age = host.get("age_seconds")
        age_txt = f"{age}s ago" if age is not None else "—"
        st.caption(
            f"Last host job: {host.get('job') or '—'} · "
            f"ok={host.get('ok')} · finished {age_txt} · "
            f"due_sweep mtime={host.get('due_sweep_mtime') or '—'}"
        )
        failures = list(host.get("failures") or [])
        if failures:
            st.warning(f"{len(failures)} open host failure(s)")
            _table(st, failures[:20])
        else:
            st.caption("No open host failures in last_run.json.")
    else:
        st.caption(
            "Host health not found "
            f"({host.get('path') or 'host_quartr/health/last_run.json'}). "
            "Run host_automation calendar|live on the host."
        )
        if host.get("due_sweep_mtime"):
            st.caption(f"due_sweep mtime={host['due_sweep_mtime']}")

    st.subheader("Alerts")
    _table(st, with_company_labels(alerts))
    st.subheader("Event run timeline")
    event_ids = sorted(
        {
            str(run.get("provider_event_id"))
            for run in data.job_runs
            if run.get("provider_event_id")
        }
    )
    selected = st.selectbox("Event", ("all", *event_ids))
    _table(
        st,
        with_company_labels(
            data.run_timeline(None if selected == "all" else selected)
        ),
    )
    st.subheader("Recent poll cycles")
    _table(st, data.poll_cycles[:50])
    st.subheader("Artifact publications")
    _table(
        st,
        [
            {
                key: row.get(key)
                for key in (
                    "provider_event_id",
                    "fingerprint",
                    "status",
                    "attempts",
                    "completed_at",
                    "manifest_uri",
                    "last_error",
                )
            }
            for row in data.artifact_publications
        ],
    )


# Roz page view radio (Signal research lives on Rank IC Research).
VIEWS = {
    "Overview": render_overview,
    "Event inbox": render_event_inbox,
    "Company history": render_company_history,
    "Dimension panel": render_dimension_heatmap,
    "Cross-company": render_cross_company,
    "Narrative vs quant": render_narrative_vs_quant,
    "Book ranks": render_book_ranks,
    "Consolidated panel": render_consolidated_panel,
    "Operations": render_operations,
    "Audit": render_audit,
}

# Rank IC Research workbench views live in rank_ic_research.py (Explore + Explain).
# Re-exported here so existing tests can import RANK_IC_VIEWS from views.

