"""Rank IC Research workbench page (Streamlit multipage).

Shares Roz's sector / custom-list universe filter via dashboard.shell session keys.
Native Explore + Explain views; production pack is read-only.
"""
from __future__ import annotations

from services.earnings_monitor.dashboard.rank_ic_research import render_rank_ic_workbench
from services.earnings_monitor.dashboard.shell import (
    configure_page,
    get_streamlit,
    load_dashboard_shell,
    render_research_status_sidebar,
)


def main() -> None:
    st = get_streamlit()
    configure_page(st, page_title="Rank IC Research")
    st.title("Rank IC Research")
    st.caption(
        "Cross-company Rank IC workbench. Company filter is shared with Roz — "
        "onboarded names appear here automatically."
    )

    ctx = load_dashboard_shell(st)
    if ctx is None:
        return

    render_research_status_sidebar(st, ctx.data)
    render_rank_ic_workbench(
        st,
        ctx.data,
        sector_tickers=ctx.sector_tickers,
        sector_choice=ctx.sector_choice,
    )


main()
