"""Streamlit renderers.

No Streamlit import occurs here.  A compatible object is passed in by the app,
which keeps these functions importable and easy to exercise in unit tests.
"""
from __future__ import annotations

from typing import Any

from .data import DashboardData


def _table(st: Any, rows: list[dict[str, Any]]) -> None:
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("No matching records.")


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{float(value):.{digits}f}"


def render_overview(st: Any, data: DashboardData) -> None:
    st.header("Roz overview")
    summary = data.overview()
    companies, quarters, active, incomplete = st.columns(4)
    companies.metric("Companies", summary["companies"])
    quarters.metric("Historical quarters", summary["quarters"])
    active.metric("Active events", summary["active_events"])
    incomplete.metric("Incomplete quarters", summary["incomplete_quarters"])
    st.caption(
        f"{summary['history_rows']:,} dimension records are loaded across "
        f"{summary['armed_events']} operational events."
    )

    st.subheader("Latest company scorecards")
    scorecards = data.latest_scorecards()
    _table(
        st,
        [
            {
                "ticker": row["ticker"],
                "latest_period": row["fiscal_period"],
                "narrative": _fmt(row["narrative_level"]),
                "change": _fmt(row["narrative_change"]),
                "quant_z": _fmt(row["quant_z"]),
                "narrative_quant_gap": _fmt(row["narrative_quant_gap"]),
                "divergences": row["divergences"],
                "dimensions": row["dimensions"],
                "incomplete": row["incomplete"],
            }
            for row in scorecards
        ],
    )
    if scorecards:
        try:
            import pandas as pd  # type: ignore

            frame = pd.DataFrame(scorecards).set_index("ticker")[
                ["narrative_level", "quant_z"]
            ]
            st.bar_chart(frame, use_container_width=True)
        except ImportError:
            st.caption("Install pandas to enable the score comparison chart.")

    st.subheader("Historical completeness")
    _table(st, data.completeness_coverage())
    events = data.event_inbox()
    if events:
        st.subheader("Recent pipeline events")
        _table(st, events[:8])
    alerts = data.operational_alerts()
    if alerts:
        st.subheader("Operational alerts")
        _table(st, alerts)


def render_event_inbox(st: Any, data: DashboardData) -> None:
    st.header("Event inbox")
    events = data.event_inbox()
    statuses = sorted({str(event.get("status")) for event in events if event.get("status")})
    status = st.selectbox("Status", ("all", *statuses))
    if status != "all":
        events = [event for event in events if event["status"] == status]
    _table(st, events)


def render_company_history(st: Any, data: DashboardData) -> None:
    st.header("Company history")
    if not data.tickers:
        st.info("No companies are available.")
        return
    ticker = st.selectbox("Company", data.tickers)
    history = data.company_history(ticker)
    st.caption(f"{len(history)} imported quarters")
    _table(st, history)
    chart_rows = [
        {
            "fiscal_period": row["fiscal_period"],
            "narrative_level": row["narrative_level"],
            "quant_z": row["quant_z"],
            "narrative_quant_gap": row["narrative_quant_gap"],
        }
        for row in history
    ]
    if chart_rows:
        st.line_chart(
            chart_rows,
            x="fiscal_period",
            y=["narrative_level", "quant_z", "narrative_quant_gap"],
        )


def render_dimension_heatmap(st: Any, data: DashboardData) -> None:
    st.header("Dimension heatmap")
    selected = st.multiselect("Companies", data.tickers, default=data.tickers[:1])
    periods = st.slider("Latest periods", min_value=4, max_value=20, value=8)
    metric_label = st.radio(
        "Signal",
        ("Narrative level", "Quant z-score", "Narrative–quant gap"),
        horizontal=True,
    )
    metric = {
        "Narrative level": "narrative_level",
        "Quant z-score": "quant_z",
        "Narrative–quant gap": "gap",
    }[metric_label]
    rows = data.dimension_heatmap(
        tickers=selected or data.tickers,
        latest_periods=periods,
    )
    if not rows:
        st.info("No dimension history matches the selected companies.")
        return
    try:
        import pandas as pd  # type: ignore

        frame = pd.DataFrame(rows)
        frame["signal"] = pd.to_numeric(frame[metric], errors="coerce")
        frame["magnitude"] = frame["signal"].abs().fillna(0) + 0.15
        st.scatter_chart(
            frame,
            x="fiscal_period",
            y="dimension",
            color="ticker",
            size="magnitude",
            use_container_width=True,
        )
    except ImportError:
        st.caption("Install pandas to enable the heatmap chart.")
    st.caption(
        "Bubble size shows absolute signal strength. The table gives direction, "
        "exact values, and narrative/quant divergence."
    )
    _table(
        st,
        [
            {
                "ticker": row["ticker"],
                "fiscal_period": row["fiscal_period"],
                "dimension": row["dimension"],
                metric: row[metric],
                "divergence": row["divergence"],
            }
            for row in rows
        ],
    )


def render_cross_company(st: Any, data: DashboardData) -> None:
    st.header("Cross-company")
    periods = st.slider("Trailing quarters", min_value=1, max_value=40, value=12)
    rows = data.cross_company(latest_periods=periods)
    _table(st, rows)
    if rows:
        try:
            import pandas as pd  # type: ignore

            frame = pd.DataFrame(rows)
            st.bar_chart(
                frame,
                x="ticker",
                y="mean_narrative_level",
                color="latest_period",
                use_container_width=True,
            )
        except ImportError:
            st.caption("Install pandas to enable the comparison chart.")


def render_narrative_vs_quant(st: Any, data: DashboardData) -> None:
    st.header("Narrative vs quant")
    selected = st.multiselect("Companies", data.tickers, default=data.tickers)
    dimension_options = ["All"] + data.dimensions
    dimension = st.selectbox("Dimension", dimension_options)
    points = data.narrative_vs_quant(
        tickers=selected,
        dimension=None if dimension == "All" else dimension,
    )
    divergences = sum(bool(point["divergence"]) for point in points)
    left, right = st.columns(2)
    left.metric("Comparable observations", len(points))
    right.metric("Divergences", divergences)
    if points:
        try:
            import pandas as pd  # type: ignore

            frame = pd.DataFrame(points)
            st.scatter_chart(
                frame,
                x="quant_z",
                y="narrative_level",
                color="ticker",
                size="divergence",
            )
        except ImportError:
            st.caption("Install pandas to enable the scatter chart.")
        _table(st, points)
    else:
        st.info("No rows have both narrative and quantitative values.")


def render_audit(st: Any, data: DashboardData) -> None:
    st.header("Audit")
    incomplete_only = st.checkbox("Show incomplete quarters only", value=False)
    audits = data.audit(incomplete_only=incomplete_only)
    incomplete = sum(bool(row["incomplete"]) for row in audits)
    left, right = st.columns(2)
    left.metric("Quarter records", len(audits))
    right.metric("Incomplete", incomplete)
    _table(st, audits)
    st.subheader("Pipeline status")
    status = data.pipeline_status()
    if status:
        _table(st, status)
    else:
        st.caption("No operational events are armed.")


def render_operations(st: Any, data: DashboardData) -> None:
    st.header("Operations")
    alerts = data.operational_alerts()
    left, right = st.columns(2)
    left.metric("Active alerts", len(alerts))
    right.metric("Recorded runs", len(data.job_runs))
    st.subheader("Alerts")
    _table(st, alerts)
    st.subheader("Event run timeline")
    event_ids = sorted(
        {
            str(run.get("provider_event_id"))
            for run in data.job_runs
            if run.get("provider_event_id")
        }
    )
    selected = st.selectbox("Event", ("all", *event_ids))
    _table(st, data.run_timeline(None if selected == "all" else selected))
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
    "Dimension heatmap": render_dimension_heatmap,
    "Cross-company": render_cross_company,
    "Narrative vs quant": render_narrative_vs_quant,
    "Operations": render_operations,
    "Audit": render_audit,
}
