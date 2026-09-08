"""Streamlit entry point — Roz home page (multipage app root).

Run with:
    streamlit run services/earnings_monitor/dashboard/app.py

Rank IC Research, Rank IC Lab, and Claims Desk are sibling
pages under ``dashboard/pages/``.
"""
from __future__ import annotations

import os
from typing import Any

from services.earnings_monitor.dashboard.data import DashboardData
from services.earnings_monitor.dashboard.shell import (
    configure_page,
    get_streamlit,
    load_dashboard_shell,
    render_quartr_sidebar,
    render_research_status_sidebar,
)
from services.earnings_monitor.dashboard.views import VIEWS


def render_app(
    *,
    st: Any | None = None,
    data: DashboardData | None = None,
    dataset_path: str | os.PathLike[str] | None = None,
) -> None:
    """Render the Roz page with injectable UI/data dependencies for tests."""
    st = st or get_streamlit()
    configure_page(st, page_title="Roz")
    st.title("Roz")
    st.caption("Earnings intelligence: live pipeline state and historical scoring")

    ctx = load_dashboard_shell(st, data=data, dataset_path=dataset_path)
    if ctx is None:
        return

    render_quartr_sidebar(st, ctx.data)
    render_research_status_sidebar(st, ctx.data)

    view_name = st.sidebar.radio("View", list(VIEWS), key="roz_view")
    VIEWS[view_name](
        st,
        ctx.data,
        sector_tickers=ctx.sector_tickers,
        sector_choice=ctx.sector_choice,
    )


def main() -> None:
    render_app()


if __name__ == "__main__":
    main()
