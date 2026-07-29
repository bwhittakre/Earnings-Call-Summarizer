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
        }
        for row in history
    ]
    if chart_rows:
        st.line_chart(chart_rows, x="fiscal_period", y=["narrative_level", "quant_z"])


def render_cross_company(st: Any, data: DashboardData) -> None:
    st.header("Cross-company")
    periods = st.slider("Trailing quarters", min_value=1, max_value=40, value=12)
    _table(st, data.cross_company(latest_periods=periods))


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


VIEWS = {
    "Event inbox": render_event_inbox,
    "Company history": render_company_history,
    "Cross-company": render_cross_company,
    "Narrative vs quant": render_narrative_vs_quant,
    "Audit": render_audit,
}
