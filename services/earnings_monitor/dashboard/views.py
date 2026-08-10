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
    narrative_quant_scatter,
    overview_pulse_chart,
    ranked_bar_chart,
)
from .company_labels import format_company_label, with_company_labels
from .data import DashboardData
from .report_static import ensure_reports_static_link, static_report_url
from .research_data import (
    artifact_universe_status,
    can_inline_html,
    format_universe_stale_message,
    html_report_meta,
    load_consolidated_panel,
    load_rank_ic_bundle,
    resolve_consolidated_html,
    resolve_rank_ic_html,
)
from .sectors import pad_company_rows

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
) -> None:
    del sector_tickers  # ops view is not sector-scoped
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


def render_narrative_vs_quant(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
) -> None:
    st.header("Narrative vs quant")
    universe = _universe(data, sector_tickers)
    if not universe:
        st.info("No companies are available.")
        return

    default = universe[:1]
    selected = _multi_tickers(
        st,
        universe,
        default=default,
        key="nvq_companies",
    )
    dimension_options = ["All"] + data.dimensions
    dimension = st.selectbox("Dimension", dimension_options, key="nvq_dimension")
    point_filter = st.radio(
        "Points",
        ("All points", "Divergences only"),
        horizontal=True,
        key="nvq_points",
    )

    points = data.narrative_vs_quant(
        tickers=selected or default,
        dimension=None if dimension == "All" else dimension,
    )
    if point_filter == "Divergences only":
        points = [point for point in points if point.get("divergence")]

    divergences = sum(bool(point["divergence"]) for point in points)
    left, right = st.columns(2)
    left.metric("Comparable observations", len(points))
    right.metric("Divergences", divergences)

    if len(selected) > 6:
        st.caption(
            f"{len(selected)} companies selected — consider narrowing the set for readability."
        )

    if points:
        _altair(
            st,
            narrative_quant_scatter(
                points,
                title="Narrative vs quant",
                color_by_company=len(selected or default) > 1,
            ),
        )
        st.caption(
            "Aligned points use a fixed readable size; divergences are larger triangles. "
            "Axes use fixed domains (narrative [-2, +2], quant z [-3, +3]). "
            "Dashed line is the narrative ≈ quant diagonal."
        )
        sorted_points = sorted(
            points,
            key=lambda point: (not bool(point.get("divergence")), str(point.get("ticker"))),
        )
        _table(st, with_company_labels(sorted_points))
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


def render_signal_research(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
) -> None:
    del sector_tickers
    st.header("Signal research")
    st.caption(
        "Embedded Rank IC report from Structured Narrative "
        "(``narrative_signal_eval.html``)."
    )
    _warn_research_universe(st, data)
    path = resolve_rank_ic_html()
    _render_html_report(
        st,
        path,
        missing_hint=(
            "Rank IC HTML report not found under cross_company/reports/. Run: "
            "python evaluate_narrative_signals.py --tickers <universe> "
            "--min-calendar-quarter 2016-Q2"
        ),
    )


def render_consolidated_panel(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
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
    if universe and len(universe) < len(data.tickers):
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
    iframe_query: dict[str, str] | None = None
    if universe and len(universe) < len(data.tickers):
        iframe_query = {"tickers": ",".join(universe)}
    _render_html_report(
        st,
        path,
        missing_hint=(
            "Consolidated panel HTML not found under cross_company/reports/. "
            "Expected consolidated_feature_panel.html (full universe). Run: "
            "python build_consolidated_panel_report.py --tickers <universe> "
            "--min-calendar-quarter 2016-Q2"
        ),
        iframe_query=iframe_query,
    )


def render_audit(
    st: Any,
    data: DashboardData,
    *,
    sector_tickers: Sequence[str] | None = None,
) -> None:
    del sector_tickers
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
) -> None:
    del sector_tickers
    st.header("Operations")
    alerts = data.operational_alerts()
    left, right = st.columns(2)
    left.metric("Active alerts", len(alerts))
    right.metric("Recorded runs", len(data.job_runs))
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


VIEWS = {
    "Overview": render_overview,
    "Event inbox": render_event_inbox,
    "Company history": render_company_history,
    "Dimension panel": render_dimension_heatmap,
    "Cross-company": render_cross_company,
    "Narrative vs quant": render_narrative_vs_quant,
    "Signal research": render_signal_research,
    "Consolidated panel": render_consolidated_panel,
    "Operations": render_operations,
    "Audit": render_audit,
}
